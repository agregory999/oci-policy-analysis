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
# common/usage_tracking.py but operates in read-only mode using a separate
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
from urllib import error as urlerror
from urllib import request

from oci_policy_analysis.common.logger import get_logger

from .model import UsageDoc

logger = get_logger(component='analytics.loader')


# Base PAR URL (read/list) provided by project owner. Object keys are
# appended directly to this base path.

ANALYTICS_PAR_BASE_URL_DEFAULT = (
    'https://objectstorage.us-ashburn-1.oraclecloud.com/p/'
    'PSeHhXAl4SS24frWNdDLzEFmFNoUnuZt1QzKfHx_K1c5G6BNl4cjS-jSmv0o7QwP/'
    'n/idxhxzdpc23m/b/policy-analysis-tracking/o/'
)


def get_analytics_par_base_url() -> str | None:
    """Return the base PAR URL for analytics, or ``None`` if disabled.

    Environment variable ``OCI_POLICY_ANALYSIS_ANALYTICS_PAR_URL`` takes
    precedence over the built-in default so the project owner can
    rotate/change buckets without a code change.
    """

    override = os.environ.get('OCI_POLICY_ANALYSIS_ANALYTICS_PAR_URL', '').strip()
    if override:
        return override
    return ANALYTICS_PAR_BASE_URL_DEFAULT or None


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
    if len(parts) < 6:
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
) -> list[tuple[str, str | None]]:
    """List usage object keys for the given date range.

    The analytics PAR currently returns a JSON listing rather than XML. The
    expected shape is a list of objects with at least a ``name`` field, e.g.:

    .. code-block:: json

        [
            {"name": "events/2024/01/01/abc123/run.json", ...},
            ...
        ]

    Returns a list of ``(object_key, tenancy_suffix)`` tuples.
    """

    logger.info('Listing analytics usage objects from PAR')

    try:
        req = request.Request(base_url, method='GET')
        with request.urlopen(req, timeout=5) as resp:  # noqa: S310
            body = resp.read()
            logger.debug(
                'Analytics listing response: status=%s, content_type=%s',
                getattr(resp, 'status', '?'),
                resp.headers.get('Content-Type'),
            )
    except (urlerror.URLError, OSError) as exc:
        logger.info('Failed to list analytics objects from PAR: %s', exc)
        return []

    try:
        data = json.loads(body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.info('Failed to decode analytics bucket listing JSON: %s', exc)
        logger.debug('Listing response body (truncated): %r', body[:400])
        return []

    objects: list[UsageObjectRef] = []
    # Support both list-of-dicts and dict-with-"objects" container shapes.
    entries = data
    if isinstance(data, dict):
        entries = data.get('objects') or data.get('items') or []

    if not isinstance(entries, list):
        logger.info('Unexpected analytics listing JSON shape: %r', type(entries))
        return []

    for item in entries:
        if not isinstance(item, dict):
            continue
        name = item.get('name') or item.get('Name')
        if not isinstance(name, str):
            continue
        ref = _parse_object_key(name)
        if ref is None:
            continue
        objects.append(ref)

    if not objects:
        logger.info('No analytics usage objects found in listing.')
        return []

    logger.info('Found %d candidate analytics objects', len(objects))

    # Apply date filters if provided.
    def _in_range(obj_date: date | None) -> bool:
        if obj_date is None:
            return True
        if start_date and obj_date < start_date:
            return False
        if end_date and obj_date > end_date:
            return False
        return True

    filtered: list[tuple[str, str | None]] = []
    for ref in objects:
        if not _in_range(ref.object_date):
            continue
        filtered.append((ref.key, ref.tenancy_suffix))

    logger.info('After date filtering, %d analytics objects remain', len(filtered))
    return filtered


def _load_single_usage_doc(base_url: str, key: str, tenancy_suffix: str | None) -> UsageDoc | None:
    """Download and parse a single usage document.

    Returns ``None`` on any failure.
    """

    url = base_url + key
    logger.debug('Loading analytics usage document: %s', url)
    try:
        req = request.Request(url, method='GET')
        with request.urlopen(req, timeout=5) as resp:  # noqa: S310
            body = resp.read()
    except (urlerror.URLError, OSError) as exc:
        logger.debug('Failed to download analytics document %s: %s', key, exc)
        return None

    try:
        raw = json.loads(body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.debug('Failed to decode analytics document %s: %s', key, exc)
        return None

    doc = UsageDoc.from_dict(raw, tenancy_suffix=tenancy_suffix)
    if doc is None:
        logger.debug('Failed to parse analytics document %s', key)
    return doc


def load_usage_docs_from_par(
    start_date: date | None,
    end_date: date | None,
) -> list[UsageDoc]:
    """Load usage documents from the configured analytics PAR.

    Returns a list of successfully parsed :class:`UsageDoc` instances.
    """

    base_url = get_analytics_par_base_url()
    if not base_url:
        logger.info('Analytics PAR URL is not configured; skipping load.')
        return []

    # Step 1: list all candidate objects in the requested date range.
    object_refs = list_usage_objects_for_dates(base_url, start_date, end_date)
    if not object_refs:
        return []

    # NOTE: We deliberately keep unknown-tenancy filtering out of this loader.
    # The UI (AnalyticsApp) already applies "Include 'unknown' tenancy" at the
    # aggregation layer by selecting which docs to pass into the aggregators.
    # Keeping the loader agnostic preserves the raw dataset for debugging and
    # alternate analysis flows.

    # Step 3: load usage documents concurrently with a small thread pool. The
    # PAR is an HTTP endpoint, so downloads are I/O bound; a handful of
    # threads is usually enough to hide latency without overwhelming the
    # service.

    docs: list[UsageDoc] = []

    def _load_pair(args: tuple[str, str | None]) -> UsageDoc | None:
        key, tenancy_suffix = args
        thread = threading.current_thread()
        logger.debug(
            '[thread %s/%s] Loading analytics document key=%s tenancy_suffix=%s',
            getattr(thread, 'name', '?'),
            getattr(thread, 'ident', '?'),
            key,
            tenancy_suffix,
        )
        return _load_single_usage_doc(base_url, key, tenancy_suffix)

    # Use a small thread pool to parallelize I/O-bound downloads from PAR.
    # Bump the worker count slightly to improve throughput without being noisy.
    with ThreadPoolExecutor(max_workers=7, thread_name_prefix='AnalyticsLoader') as executor:
        future_to_ref = {executor.submit(_load_pair, ref): ref for ref in object_refs}
        for future in as_completed(future_to_ref):
            ref = future_to_ref[future]
            try:
                doc = future.result()
            except Exception as exc:  # defensive: never let one failure break all
                logger.debug('Exception while loading analytics document %s: %s', ref[0], exc)
                continue
            if doc is not None:
                docs.append(doc)

    logger.info('Loaded %d valid analytics usage documents', len(docs))
    return docs


__all__ = [
    'ANALYTICS_PAR_BASE_URL_DEFAULT',
    'get_analytics_par_base_url',
    'list_usage_objects_for_dates',
    'load_usage_docs_from_par',
]
