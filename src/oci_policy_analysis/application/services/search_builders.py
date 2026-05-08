"""Helpers to build PolicySearch filters from raw UI inputs."""

from __future__ import annotations

from collections.abc import Iterable

from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.common.models import PolicySearch

LOGGER = get_logger(component='search_builders')


def _split_pipe(value: str | None) -> list[str]:
    """Split pipe-delimited filter value into normalized parts.

    Args:
        value: Raw pipe-delimited string value.

    Returns:
        list[str]: Non-empty trimmed filter values.
    """
    if not value:
        return []
    return [part.strip() for part in value.split('|') if part.strip()]


def build_policy_search_from_filters(
    *,
    subject: str | None = None,
    action: str | None = None,
    verb: str | None = None,
    resource: str | None = None,
    permission: str | None = None,
    location: str | None = None,
    compartment_path: str | None = None,
    statement_text: str | None = None,
    policy_name: str | None = None,
    effective_path: str | None = None,
    conditions: str | None = None,
    valid: bool | None = None,
) -> PolicySearch:
    """Build a ``PolicySearch`` from raw filter strings.

    Args:
        subject: Subject filter value.
        action: Action value; supports allow/deny/both.
        verb: Verb filter value.
        resource: Resource filter value.
        permission: Permission filter value.
        location: Location filter value.
        compartment_path: Compartment path filter value.
        statement_text: Statement text filter value.
        policy_name: Policy name filter value.
        effective_path: Effective path filter value.
        conditions: Conditions filter value.
        valid: Optional validity filter.

    Returns:
        PolicySearch: Normalized filter payload.
    """
    LOGGER.info('Building policy search from raw filters')

    filters: PolicySearch = {}
    if subject:
        filters['subject'] = _split_pipe(subject)

    action_value = (action or 'both').lower()
    if action_value == 'allow':
        filters['action'] = ['allow']
    elif action_value == 'deny':
        filters['action'] = ['deny']
    else:
        filters['action'] = ['allow', 'deny', 'unknown']

    if verb:
        allowed_verbs = {'inspect', 'read', 'use', 'manage'}
        verbs = [v for v in _split_pipe(verb) if v in allowed_verbs]
        if verbs:
            filters['verb'] = verbs  # type: ignore[assignment]

    if resource:
        filters['resource'] = _split_pipe(resource)
    if permission:
        filters['permission'] = _split_pipe(permission)
    if location:
        filters['location'] = _split_pipe(location)
    if compartment_path:
        filters['compartment_path'] = _split_pipe(compartment_path)
    if statement_text:
        filters['statement_text'] = _split_pipe(statement_text)
    if policy_name:
        filters['policy_name'] = _split_pipe(policy_name)
    if effective_path:
        filters['effective_path'] = _split_pipe(effective_path)
    if conditions:
        filters['conditions'] = _split_pipe(conditions)
    if valid is not None:
        filters['valid'] = valid
    return filters


def build_policy_search_from_dict(payload: dict[str, object]) -> PolicySearch:
    """Build ``PolicySearch`` from dictionary payload values.

    Args:
        payload: Raw payload containing strings, booleans, or iterables.

    Returns:
        PolicySearch: Normalized filter payload.
    """
    LOGGER.info('Building policy search from payload keys=%s', sorted(payload.keys()))

    def _as_str(value: object | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, Iterable):
            return '|'.join([str(v) for v in value if str(v).strip()])
        return str(value)

    valid_value = payload.get('valid')
    return build_policy_search_from_filters(
        subject=_as_str(payload.get('subject')),
        action=_as_str(payload.get('action')),
        verb=_as_str(payload.get('verb')),
        resource=_as_str(payload.get('resource')),
        permission=_as_str(payload.get('permission')),
        location=_as_str(payload.get('location')),
        compartment_path=_as_str(payload.get('compartment_path')),
        statement_text=_as_str(payload.get('statement_text')),
        policy_name=_as_str(payload.get('policy_name')),
        effective_path=_as_str(payload.get('effective_path')),
        conditions=_as_str(payload.get('conditions')),
        valid=valid_value if isinstance(valid_value, bool) else None,
    )
