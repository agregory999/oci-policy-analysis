"""Lightweight runtime access-key gate for the web UI."""

from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

from oci_policy_analysis.common.logger import get_logger

logger = get_logger(component='web_auth')

_RUNTIME_ACCESS_KEY = str(uuid4())
_RUNTIME_KEY_FINGERPRINT = sha256(_RUNTIME_ACCESS_KEY.encode('utf-8')).hexdigest()

# Intentionally logged at CRITICAL so operators can retrieve the current session key.
logger.critical(
    (
        '\n\n'
        '============================================================\n'
        '  WEB UI ACCESS KEY REQUIRED\n'
        '============================================================\n'
        'Use this runtime key in the browser login modal to unlock\n'
        'all web pages for this server session.\n\n'
        'WEB_UI_RUNTIME_ACCESS_KEY: %s\n\n'
        'Note: This key rotates each time the web server restarts.\n'
        '============================================================\n'
    ),
    _RUNTIME_ACCESS_KEY,
)


def verify_access_key(candidate: str) -> bool:
    """Return True when a candidate key matches the runtime startup key."""
    return bool(candidate) and candidate.strip() == _RUNTIME_ACCESS_KEY


def current_key_fingerprint() -> str:
    """Return stable fingerprint for the current runtime key generation."""
    return _RUNTIME_KEY_FINGERPRINT
