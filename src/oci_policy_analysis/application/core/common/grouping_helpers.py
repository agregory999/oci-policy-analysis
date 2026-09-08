"""Semantic grouping helpers shared by recommendations and consolidation plans."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class SimilarPrincipalStatementGroup:
    """Statements safe to replace with one multi-principal policy statement."""

    statements: list[dict]
    subject_type: str
    principals: list[tuple[str, str]]


def named_principals(statement: dict) -> list[tuple[str, str]] | None:
    """Return canonical named group principals, or ``None`` for unsafe inputs."""
    subject_type = str(statement.get('subject_type') or '').casefold()
    if subject_type not in {'group', 'dynamic-group'}:
        return None
    subjects = statement.get('subject') or []
    if not isinstance(subjects, list) or not subjects:
        return None
    principals: list[tuple[str, str]] = []
    for subject in subjects:
        if not isinstance(subject, tuple | list) or len(subject) != 2:
            return None
        domain, name = (str(subject[0] or 'Default').strip(), str(subject[1] or '').strip())
        if not domain or not name:
            return None
        principals.append((domain, name))
    return principals


def statement_grouping_key(statement: dict) -> tuple | None:
    """Return the non-principal semantic identity required for a safe merge.

    Policy placement is part of the key. It lets the grouped replacement live in
    the same compartment as every source statement, preserving the original
    location clause instead of changing policy semantics during grouping.
    """
    principals = named_principals(statement)
    if principals is None or not statement.get('valid', True):
        return None
    action = str(statement.get('action') or '').casefold()
    subject_type = str(statement.get('subject_type') or '').casefold()
    effective_path = str(statement.get('effective_path') or '').strip()
    policy_compartment = str(statement.get('compartment_ocid') or '').strip()
    location = str(statement.get('location') or '').strip()
    conditions = str(statement.get('conditions_where_clause') or statement.get('conditions') or '').strip()
    verb = str(statement.get('verb') or '').casefold()
    resource = str(statement.get('resource') or '').casefold()
    permissions = tuple(sorted({str(permission).casefold() for permission in statement.get('permission') or []}))
    comments = str(statement.get('comments') or '').strip()
    has_matching_access_clause = bool(verb and resource) or bool(permissions)
    if not all((action, subject_type, effective_path, policy_compartment)) or not has_matching_access_clause:
        return None
    return (
        action,
        subject_type,
        effective_path.casefold(),
        policy_compartment,
        location.casefold(),
        conditions.casefold(),
        verb,
        resource,
        permissions,
        comments,
    )


def find_similar_principal_statement_groups(statements: list[dict]) -> list[SimilarPrincipalStatementGroup]:
    """Find groups differing only by one or more named group principals."""
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for statement in statements:
        key = statement_grouping_key(statement)
        if key is not None:
            grouped[key].append(statement)

    results: list[SimilarPrincipalStatementGroup] = []
    for key, candidates in grouped.items():
        if len(candidates) < 2:
            continue
        principal_map: dict[tuple[str, str], tuple[str, str]] = {}
        for candidate in candidates:
            for domain, name in named_principals(candidate) or []:
                principal_map.setdefault((domain.casefold(), name.casefold()), (domain, name))
        if len(principal_map) < 2:
            continue
        results.append(
            SimilarPrincipalStatementGroup(
                statements=sorted(candidates, key=lambda statement: str(statement.get('internal_id') or '')),
                subject_type=key[1],
                principals=[principal_map[item] for item in sorted(principal_map)],
            )
        )
    return results


def render_grouped_statement(statement: dict, principals: list[tuple[str, str]]) -> str:
    """Replace the subject span with canonical domain/name principals.

    The rest of the original statement is retained byte-for-byte, which avoids
    accidentally changing verb, resource, location, or where-clause semantics.
    """
    action = str(statement.get('action') or '').casefold()
    subject_type = str(statement.get('subject_type') or '').casefold()
    rendered_principals = ', '.join(f"'{domain}'/'{name}'" for domain, name in principals)
    pattern = rf'^(?P<prefix>{re.escape(action)}\s+{re.escape(subject_type)}\s+).+?(?P<suffix>\s+to\s+.+)$'
    raw = str(statement.get('statement_text') or '').strip()
    match = re.match(pattern, raw, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        raise ValueError('Statement text does not match a regular allow/deny named-principal statement.')
    return f'{match.group("prefix")}{rendered_principals}{match.group("suffix")}'
