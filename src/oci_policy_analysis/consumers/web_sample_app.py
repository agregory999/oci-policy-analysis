"""Minimal web consumer stub using the new service scaffolding.

This does not replace the existing app. It is a lightweight skeleton for
future FastAPI/HTTP integration.
"""

from __future__ import annotations

from dataclasses import asdict

from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.application.services.load_service import LoadService


def get_status() -> dict[str, object]:
    """Placeholder status endpoint handler."""
    ctx = AppContext.from_settings(settings={})
    service = LoadService(ctx)
    caches = ctx.cache.get_available_cache(tenancy_name=None)
    if not caches:
        return {'ok': False, 'error': 'No caches found. Load a tenancy first to create one.'}
    cache_name = caches[0]
    result = service.load_from_cache(cache_name=cache_name)
    payload = asdict(result)
    return {'ok': result.success, 'result': payload}


def main() -> None:
    # Placeholder entrypoint for future FastAPI startup.
    # When ready, wire this into FastAPI and expose routes calling get_status.
    payload = get_status()
    print(payload)


if __name__ == '__main__':
    main()
