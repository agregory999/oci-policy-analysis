##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# analytics/loader.py
#
# Loader utilities for reading anonymous usage tracking documents from an
# Object Storage PAR. This mirrors the shape and conventions used in
# application/core/support/usage_tracking.py but operates in read-only mode using a separate
# PAR URL.
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

"""Loader functions for usage analytics.

This module knows how to:

* Resolve the analytics PAR base URL from environment or default.
* List candidate usage objects from the bucket XML listing.
* Filter objects by ``events/YYYY/MM/DD/<tenancy_suffix>/<run_id>.json``
  pattern and date range.
* Download and parse each document into :class:`UsageDoc` instances.

All failures are logged and skipped so that a single bad object does not
prevent analytics from loading.
"""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from urllib import request

from oci_policy_analysis.application.core.support.logger import get_logger

from .model import UsageDoc

logger = get_logger(component='analytics.loader')


def get_analytics_par_base_url() -> str | None:
    """Return the base PAR URL for analytics, or ``None`` if disabled.

    Environment variable ``OCI_POLICY_ANALYSIS_ANALYTICS_PAR_URL`` controls
    the endpoint. No default is bundled in code.
    """

    override = os.environ.get('OCI_POLICY_ANALYSIS_ANALYTICS_PAR_URL', '').strip()
    if override:
        return override
    return None


@dataclass
class UsageObjectRef:
    """Reference to a single usage object in Object Storage."""

    key: str
    tenancy_suffix: str | None
    object_date: date | None


def _parse_object_key(key: str) -> UsageObjectRef | None:
    """Parse an object key into its components if it matches the events path.

    Expected pattern::

        events/YYYY/MM/DD/<tenancy_suffix>/<run_id>.json
    """

    if not key.startswith('events/'):
        return None

    parts = key.split('/')
    # events, YYYY, MM, DD, tenancy_suffix, filename
    if len(parts) != 6 or not parts[-1].endswith('.json') or any(part in {'.', '..'} for part in parts):
        return None

    try:
        year = int(parts[1])
        month = int(parts[2])
        day = int(parts[3])
        obj_date = date(year, month, day)
    except ValueError:
        logger.debug('Skipping object with invalid date components: %s', key)
        return None

    tenancy_suffix = parts[4] or None
    return UsageObjectRef(key=key, tenancy_suffix=tenancy_suffix, object_date=obj_date)


def list_usage_objects_for_dates(
    base_url: str,
    start_date: date | None,
    end_date: date | None,
    *,
    strict: bool = False,
    cancelled: threading.Event | None = None,
) -> list[tuple[str, str | None]]:
    """List all pages of usage JSON objects, including legacy listing shapes.

    Args:
        base_url: Read/list PAR base URL, never logged.
        start_date: Inclusive lower object-date bound.
        end_date: Inclusive upper object-date bound.
        strict: Raise a sanitized error instead of returning an empty list on failure.
        cancelled: Stop pagination after the current request completes.

    Returns:
        list[tuple[str, str | None]]: Unique object keys and tenancy suffixes.

    Raises:
        ValueError: Invalid dates, listing shape or endpoint failure in strict mode.
    """
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    from xml.etree import ElementTree

    if start_date and end_date and start_date > end_date:
        raise ValueError('Start date must precede end date.')
    objects, seen_pages = {}, set()
    next_start = None
    try:
        while True:
            if cancelled is not None and cancelled.is_set():
                return []
            parts = urlsplit(base_url)
            query = dict(parse_qsl(parts.query))
            if next_start is not None:
                query['start'] = next_start
            url = urlunsplit(parts._replace(query=urlencode(query)))
            with request.urlopen(request.Request(url, method='GET'), timeout=5) as response:  # noqa: S310
                body = response.read()
            try:
                data = json.loads(body)
            except (ValueError, UnicodeDecodeError):
                root = ElementTree.fromstring(body)

                def local(tag):
                    return tag.rsplit('}', 1)[-1]

                if local(root.tag) not in {'ListBucketResult', 'ListObjects', 'ListObjectsResult'}:
                    raise ValueError('Unexpected XML listing') from None
                if any(
                    (local(child.tag) == 'IsTruncated' and (child.text or '').lower() == 'true')
                    or (local(child.tag) in {'NextMarker', 'NextContinuationToken', 'NextStartWith'} and child.text)
                    for child in root.iter()
                ):
                    raise ValueError('Truncated XML listing requires a native JSON endpoint') from None
                data = {
                    'objects': [{'name': child.text} for child in root.iter() if local(child.tag) in {'Key', 'Name'}],
                    'nextStartWith': next(
                        (child.text for child in root.iter() if local(child.tag) in {'NextMarker', 'NextStartWith'}),
                        None,
                    ),
                }
            if isinstance(data, dict) and not any(key in data for key in ('objects', 'items')):
                raise ValueError('Unexpected listing format')
            entries = (
                data
                if isinstance(data, list)
                else data.get('objects', data.get('items', []))
                if isinstance(data, dict)
                else None
            )
            if not isinstance(entries, list):
                raise ValueError('Unexpected listing format')
            for item in entries:
                if not isinstance(item, dict):
                    continue
                key = item.get('name') or item.get('Name')
                ref = _parse_object_key(key) if isinstance(key, str) else None
                if (
                    ref
                    and not (start_date and ref.object_date < start_date)
                    and not (end_date and ref.object_date > end_date)
                ):
                    objects[ref.key] = ref.tenancy_suffix
            next_start = data.get('nextStartWith') if isinstance(data, dict) else None
            if not next_start:
                break
            if not isinstance(next_start, str) or next_start in seen_pages:
                raise ValueError('Invalid/repeated pagination marker')
            seen_pages.add(next_start)
        return list(objects.items())
    except Exception as exc:
        # PAR URLs are bearer credentials: never expose URL-bearing exception text.
        logger.info('Analytics listing failed: %s', type(exc).__name__)
        if strict:
            raise ValueError(
                'Unable to list usage data. Check the read/list PAR, expiry, listing permission and connection.'
            ) from None
        return []


def _load_single_usage_doc(base_url: str, key: str, tenancy_suffix: str | None) -> UsageDoc | None:
    """Download one document, tolerating malformed historical records."""
    from urllib.parse import quote, urlsplit, urlunsplit

    parts = urlsplit(base_url)
    url = urlunsplit(parts._replace(path=parts.path.rstrip('/') + '/' + quote(key, safe='/'), query=''))
    try:
        with request.urlopen(request.Request(url, method='GET'), timeout=5) as response:  # noqa: S310
            raw = json.loads(response.read())
        return UsageDoc.from_dict(raw, tenancy_suffix=tenancy_suffix)
    except Exception as exc:
        logger.debug('Analytics document skipped: %s', type(exc).__name__)
        return None


@dataclass
class UsageLoadResult:
    """Loaded documents plus visible coverage counts for incomplete reads."""

    docs: list[UsageDoc]
    listed: int
    skipped: int


def load_usage_report(
    start_date: date | None,
    end_date: date | None,
    *,
    base_url: str | None = None,
    cancelled: threading.Event | None = None,
) -> UsageLoadResult:
    """Read usage documents concurrently without writing bucket objects.

    Args:
        start_date: Inclusive lower object-date bound, or all history.
        end_date: Inclusive upper object-date bound.
        base_url: Explicit read/list URL; otherwise resolve the environment variable.
        cancelled: Optional cooperative cancellation flag.

    Returns:
        UsageLoadResult: Successful documents and skipped-object counts.

    Raises:
        ValueError: Missing endpoint or failed bucket listing.
    """
    base_url = base_url or get_analytics_par_base_url()
    if not base_url:
        raise ValueError('Configure OCI_POLICY_ANALYSIS_ANALYTICS_PAR_URL or enter a read/list PAR URL.')
    refs = list_usage_objects_for_dates(base_url, start_date, end_date, strict=True, cancelled=cancelled)
    docs = []

    def load(ref):
        if cancelled is not None and cancelled.is_set():
            return None
        return _load_single_usage_doc(base_url, *ref)

    with ThreadPoolExecutor(max_workers=7, thread_name_prefix='AnalyticsLoader') as executor:
        futures = [executor.submit(load, ref) for ref in refs]
        for future in as_completed(futures):
            doc = future.result()
            if doc is not None:
                docs.append(doc)
    return UsageLoadResult(docs, len(refs), len(refs) - len(docs))


def load_usage_docs_from_par(start_date: date | None, end_date: date | None) -> list[UsageDoc]:
    """Retain the legacy Tk loader's best-effort list-returning API."""
    try:
        return load_usage_report(start_date, end_date).docs
    except ValueError:
        return []


__all__ = [
    'get_analytics_par_base_url',
    'list_usage_objects_for_dates',
    'load_usage_docs_from_par',
    'load_usage_report',
    'UsageLoadResult',
]
