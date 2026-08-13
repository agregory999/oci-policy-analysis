"""Detect policy statements fully covered by applicable allow grants."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from oci_policy_analysis.application.core.common.policy_helpers import calculate_principal_key


def _path_segments(path: object) -> tuple[str, ...]:
    """Return a normalized, segment-aware compartment path."""
    return tuple(segment.casefold() for segment in str(path or '').strip('/').split('/') if segment)


def _is_strict_ancestor(ancestor_path: object, candidate_path: object) -> bool:
    """Return whether ``ancestor_path`` is strictly above ``candidate_path``."""
    ancestor = _path_segments(ancestor_path)
    candidate = _path_segments(candidate_path)
    return bool(ancestor and len(ancestor) < len(candidate) and candidate[: len(ancestor)] == ancestor)


def _scope_relationship(evidence_path: object, candidate_path: object) -> str | None:
    """Return the applicable scope relationship, if any.

    A statement at the same effective scope can make another statement
    redundant just as an ancestor statement can. Descendant scopes never
    provide coverage for the candidate.
    """
    if _path_segments(evidence_path) == _path_segments(candidate_path):
        return 'Same scope'
    if _is_strict_ancestor(evidence_path, candidate_path):
        return 'Ancestor'
    return None


def _principal_keys(statement: dict[str, Any]) -> frozenset[str]:
    """Return canonical principal keys for a policy statement."""
    principals = statement.get('principals')
    if isinstance(principals, list):
        keys = {
            str(principal.get('principal_key') or '').casefold()
            for principal in principals
            if isinstance(principal, dict) and principal.get('principal_key')
        }
        if keys:
            return frozenset(keys)

    subject_type = str(statement.get('subject_type') or '').strip()
    subject = statement.get('subject')
    if subject_type in {'any-user', 'any-group'}:
        return frozenset({subject_type})
    items = subject if isinstance(subject, list) else [subject]
    keys: set[str] = set()
    for item in items:
        if isinstance(item, tuple | list) and len(item) >= 2:
            domain, name = item[0], item[1]
        else:
            domain, name = None, item
        if str(name or '').strip():
            keys.add(calculate_principal_key(subject_type, domain, str(name)).casefold())
    return frozenset(keys)


def _permissions(repo: Any, statement: dict[str, Any]) -> frozenset[str]:
    """Return resolved permissions, falling back to repository reference data."""
    raw = statement.get('permission')
    if isinstance(raw, str):
        raw = [raw]
    permissions = {str(permission).casefold() for permission in (raw or []) if str(permission).strip()}
    if permissions:
        return frozenset(permissions)
    reference = getattr(repo, 'permission_reference_repo', None)
    if reference is None:
        return frozenset()
    derived = reference.get_permissions(
        entity=str(statement.get('resource') or ''),
        verb=str(statement.get('verb') or ''),
        action=str(statement.get('action') or 'allow'),
    )
    return frozenset(str(permission).casefold() for permission in (derived or []) if str(permission).strip())


class SupersessionAnalyzer:
    """Find statements fully covered by applicable grants.

    Conditional ancestor grants never provide automatic coverage. An
    unconditional statement at the same scope or an ancestor scope can cover
    a conditional candidate; that result explicitly notes that the candidate
    restriction is ineffective. Conditional evidence is retained for review,
    but is never used to prove complete coverage.
    """

    def analyze(self, repo: Any) -> list[dict[str, Any]]:
        """Return complete-supersession findings for statements in ``repo``.

        Args:
            repo: Loaded policy repository containing regular statements and
                permission reference data.

        Returns:
            Directed candidate-to-ancestor coverage findings suitable for
            review as removable candidates.
        """
        statements = [
            statement
            for statement in (getattr(repo, 'regular_statements', []) or [])
            if isinstance(statement, dict)
            and str(statement.get('action') or 'allow').casefold() == 'allow'
            and statement.get('valid', True) is not False
            and statement.get('effective_path')
        ]
        indexed: dict[frozenset[str], list[dict[str, Any]]] = defaultdict(list)
        for statement in statements:
            keys = _principal_keys(statement)
            if keys:
                indexed[keys].append(statement)

        findings: list[dict[str, Any]] = []
        for candidate in statements:
            candidate_id = str(candidate.get('internal_id') or '')
            candidate_permissions = _permissions(repo, candidate)
            keys = _principal_keys(candidate)
            if not candidate_id or not candidate_permissions or not keys:
                continue
            unconditional_evidence: list[tuple[dict[str, Any], frozenset[str], str]] = []
            conditional_evidence: list[tuple[dict[str, Any], frozenset[str], str]] = []
            for statement in indexed[keys]:
                if statement.get('internal_id') == candidate_id:
                    continue
                relationship = _scope_relationship(statement.get('effective_path'), candidate.get('effective_path'))
                if relationship is None:
                    continue
                permissions = _permissions(repo, statement)
                if permissions:
                    overlap = permissions & candidate_permissions
                    if not overlap:
                        continue
                    target = (
                        conditional_evidence
                        if str(statement.get('conditions') or '').strip()
                        else unconditional_evidence
                    )
                    target.append((statement, overlap, relationship))

            covered = (
                set().union(*(permissions for _, permissions, _ in unconditional_evidence))
                if unconditional_evidence
                else set()
            )
            if not candidate_permissions.issubset(covered):
                continue
            remaining = set(candidate_permissions)
            selected: list[tuple[dict[str, Any], frozenset[str], str]] = []
            for statement, permissions, relationship in sorted(
                unconditional_evidence,
                key=lambda item: (
                    0 if item[2] == 'Same scope' else 1,
                    -len(_path_segments(item[0].get('effective_path'))),
                    str(item[0].get('policy_name') or ''),
                ),
            ):
                contribution = permissions & remaining
                if contribution:
                    selected.append((statement, frozenset(contribution), relationship))
                    remaining.difference_update(contribution)
                if not remaining:
                    break
            if remaining:
                continue

            selected_ids = {str(statement.get('internal_id') or '') for statement, _, _ in selected}
            all_unconditional_evidence = selected + [
                (statement, permissions, relationship)
                for statement, permissions, relationship in sorted(
                    unconditional_evidence,
                    key=lambda item: (
                        0 if item[2] == 'Same scope' else 1,
                        -len(_path_segments(item[0].get('effective_path'))),
                        str(item[0].get('policy_name') or ''),
                    ),
                )
                if str(statement.get('internal_id') or '') not in selected_ids
            ]
            conditional_candidate = bool(str(candidate.get('conditions') or '').strip())
            relevant_conditionals = sorted(
                conditional_evidence,
                key=lambda item: (item[2] != 'Same scope', str(item[0].get('policy_name') or '')),
            )
            base_classification = 'Single Statement' if len(selected) == 1 else 'Combined Statements'
            classification = f'{base_classification} (Review)' if relevant_conditionals else base_classification
            if relevant_conditionals:
                notes = (
                    'Review required: one or more conditional statements also grant part of this permission set. '
                    'They are shown as evidence but are not used to prove complete coverage.'
                )
            elif conditional_candidate:
                notes = (
                    'The candidate has a where clause, but an unconditional applicable statement grants the same '
                    'permissions; the candidate condition does not reduce effective access.'
                )
            else:
                notes = 'All candidate permissions are granted by unconditional applicable policy statements.'
            findings.append(
                {
                    'statement_internal_id': candidate_id,
                    'classification': classification,
                    'candidate_permissions': sorted(candidate_permissions),
                    'covered_permissions': sorted(candidate_permissions),
                    'notes': notes,
                    'evidence': [
                        {
                            'internal_id': str(statement.get('internal_id') or ''),
                            'policy_name': str(statement.get('policy_name') or ''),
                            'effective_path': str(statement.get('effective_path') or ''),
                            'statement_text': str(statement.get('statement_text') or ''),
                            'covered_permissions': sorted(contribution),
                            'relationship': relationship,
                            'conditional': False,
                        }
                        for statement, contribution, relationship in all_unconditional_evidence
                    ]
                    + [
                        {
                            'internal_id': str(statement.get('internal_id') or ''),
                            'policy_name': str(statement.get('policy_name') or ''),
                            'effective_path': str(statement.get('effective_path') or ''),
                            'statement_text': str(statement.get('statement_text') or ''),
                            'covered_permissions': sorted(overlap),
                            'relationship': relationship,
                            'conditional': True,
                        }
                        for statement, overlap, relationship in relevant_conditionals
                    ],
                }
            )
        return findings
