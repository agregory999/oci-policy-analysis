"""Bounded, process-local OCI call metadata independent of logging and snapshots."""

import threading
import time
from collections import deque
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
from http.client import responses
from urllib.parse import urlsplit, urlunsplit

_operation = ContextVar('opa_api_operation', default=None)
_instrument_lock = threading.RLock()


class ApiCallJournal:
    """Retain bounded metadata from concurrent API calls without writing to disk.

    Args:
        capacity: Maximum completed call records retained in memory.

    Notes:
        Contains metadata only: no request/response bodies, credentials, or raw
        headers. Sequence numbers survive clearing so GUI cursors remain valid.
        Pagination/retry attempts are separate records when using OCI SDK clients.
    """

    def __init__(self, capacity=5000):
        self._rows = deque(maxlen=capacity)
        self._lock = threading.RLock()
        self._revision = 0
        self._dropped = 0

    def append(self, record):
        """Append a completed call, evicting older successes before errors when full.

        Args:
            record: Scalar diagnostic metadata produced by the call observer.
        """
        with self._lock:
            self._revision += 1
            if len(self._rows) == self._rows.maxlen:
                self._dropped += 1
                # Keep early collection failures available after a large load
                # completes, rather than replacing them with later successes.
                success = next((index for index, row in enumerate(self._rows) if row.get('outcome') != 'Error'), None)
                if success is not None:
                    del self._rows[success]
                elif record.get('outcome') != 'Error':
                    return
            self._rows.append({**record, 'sequence': self._revision})

    def snapshot(self, revision=None):
        """Return a revision, detached rows, and eviction count under one lock."""
        with self._lock:
            if revision == self._revision:
                return self._revision, None, self._dropped
            return self._revision, [dict(row) for row in self._rows], self._dropped

    def clear(self):
        """Forget process-local metadata without touching application log files."""
        with self._lock:
            self._rows.clear()
            self._dropped = 0
            self._revision += 1


API_CALLS = ApiCallJournal()


def _endpoint(value):
    text = str(value or '')
    if ' https://' in text or ' http://' in text:
        text = text.split(' ', 1)[1]
    try:
        parts = urlsplit(text)
    except ValueError:
        return text.split('?', 1)[0]
    if parts.scheme:
        host = parts.hostname or ''
        return urlunsplit((parts.scheme, host, parts.path, '', ''))
    return text.split('?', 1)[0]


def _record(
    label, started, duration, response=None, error=None, *, endpoint='', method='', tenancy='', target='', journal=None
):
    journal = journal if journal is not None else API_CALLS
    request = getattr(response, 'request', None) or getattr(error, 'original_request', None)
    endpoint = _endpoint(getattr(error, 'request_endpoint', None) or getattr(request, 'url', None) or endpoint)
    status = getattr(error, 'status', None) if error else getattr(response, 'status', None)
    if not isinstance(status, int):
        status = None
    code = str(getattr(error, 'code', '') or (type(error).__name__ if error else ''))
    headers = getattr(error if error else response, 'headers', None) or {}
    reason = str(getattr(error, 'message', '') or (str(error) if error else responses.get(status, 'Completed')))
    hint = ''
    if status == 404 and ('get_policy' in label or getattr(error, 'operation_name', '') == 'get_policy'):
        hint = (
            'Identity could not retrieve this policy. When loading through Resource Search, '
            'this can be a stale search result after deletion (including consolidation), or insufficient permission. '
            'A 404 does not confirm deletion. The policy was not collected; inventory coverage is incomplete.'
        )
    journal.append(
        {
            'started_at': started,
            'operation': label,
            'duration_ms': round(duration * 1000, 2),
            'outcome': 'Error' if error else 'Success',
            'http_status': status,
            'code': code,
            'reason': reason[:4000],
            'request_id': str(
                getattr(error if error else response, 'request_id', '') or headers.get('opc-request-id', '')
            ),
            'method': str(getattr(request, 'method', '') or method),
            'endpoint': endpoint,
            'tenancy_ocid': str(tenancy or ''),
            'target': str(target or ''),
            'interpretation': hint,
        }
    )


def api_error_summary(error: Exception) -> str:
    """Return a concise error reason without SDK troubleshooting boilerplate.

    Args:
        error: OCI ServiceError or a local collection exception.

    Returns:
        str: HTTP status, service code, reason, and request ID where available.
    """
    status = getattr(error, 'status', None)
    if status is not None:
        return (
            f'HTTP {status} · {getattr(error, "code", "")} · {getattr(error, "message", "")} '
            f'· request={getattr(error, "request_id", "")}'
        )
    return f'{type(error).__name__}: {error}'


class ApiCallObservation:
    """Observe a repository operation and each underlying SDK HTTP attempt.

    Args:
        label: Application operation label.
        fn: Bound SDK method or pagination helper.
        args: Positional call arguments; used only to find a paginated SDK method.
        kwargs: Call arguments; only allowlisted resource IDs enter metadata.
        tenancy: Tenancy ID for associating calls across snapshot reloads.

    Notes:
        Finish in a finally block. Test doubles/non-SDK helpers produce one
        logical-operation record; no invented HTTP status is assigned to them.
    """

    def __init__(self, label, fn, args, kwargs, tenancy=''):
        self.label, self.tenancy = label, tenancy
        self.target = next(
            (
                str(kwargs[key])
                for key in ('policy_id', 'compartment_id', 'domain_id', 'group_id', 'user_id')
                if kwargs.get(key)
            ),
            '',
        )
        self.started = datetime.now(UTC).isoformat(timespec='milliseconds')
        self.start = time.perf_counter()
        self.captured = 0
        self.token = _operation.set(self)
        for method in (fn, *args):
            client = getattr(method, '__self__', None)
            if client is not None and hasattr(client, 'base_client'):
                _instrument(client, tenancy)

    def finish(self, response=None, error=None):
        """Record a fallback operation when no SDK attempts were observed, then detach."""
        try:
            if not self.captured:
                _record(
                    self.label,
                    self.started,
                    time.perf_counter() - self.start,
                    response,
                    error,
                    tenancy=self.tenancy,
                    target=self.target,
                )
        finally:
            _operation.reset(self.token)


def _instrument(client, tenancy):
    base = client.base_client
    with _instrument_lock:
        if getattr(base, '_opa_api_calls_instrumented', False):
            return
        original = getattr(base, 'call_api', None)
        if not callable(original):
            return

        @wraps(original)
        def call_api(resource_path, method, *args, **kwargs):
            observation = _operation.get()
            label = (
                observation.label
                if observation
                else f'{type(client).__name__}.{kwargs.get("operation_name") or resource_path}'
            )
            started = datetime.now(UTC).isoformat(timespec='milliseconds')
            start = time.perf_counter()
            result, error = None, None
            try:
                result = original(resource_path, method, *args, **kwargs)
                return result
            except Exception as exc:
                error = exc
                raise
            finally:
                if observation:
                    observation.captured += 1
                path = resource_path
                for key, value in (kwargs.get('path_params') or {}).items():
                    path = path.replace('{' + key + '}', str(value))
                _record(
                    label,
                    started,
                    time.perf_counter() - start,
                    result,
                    error,
                    endpoint=str(getattr(base, 'endpoint', '') or '') + path,
                    method=method,
                    tenancy=observation.tenancy if observation else tenancy,
                    target=observation.target if observation else '',
                )

        base.call_api = call_api
        base._opa_api_calls_instrumented = True
