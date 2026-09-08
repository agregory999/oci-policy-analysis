"""Shared presentation-ready consolidation opportunity builder."""

from __future__ import annotations

import hashlib
from typing import Any


def _opportunity_id(opportunity_type: str, statement_ids: list[str]) -> str:
    material = f'{opportunity_type}:{",".join(sorted(statement_ids))}'
    return hashlib.sha256(material.encode('utf-8')).hexdigest()[:12]


def _members(repo: Any, statement_ids: list[str]) -> list[dict[str, str]]:
    by_id = {
        str(statement.get('internal_id') or ''): statement
        for statement in (getattr(repo, 'regular_statements', []) or [])
    }
    return [
        {
            'internal_id': statement_id,
            'policy_name': str(statement.get('policy_name') or ''),
            'policy_ocid': str(statement.get('policy_ocid') or ''),
            'statement_text': str(statement.get('statement_text') or ''),
        }
        for statement_id in statement_ids
        if (statement := by_id.get(statement_id))
    ]


def _commonality(finding: dict[str, Any]) -> str:
    return ' | '.join(
        str(value)
        for value in [finding.get('Principal'), finding.get('Service/Resource'), finding.get('Compartment')]
        if value
    )


def _proposed_statement(detail: object) -> str:
    marker = 'Proposed statement: '
    text = str(detail or '')
    return text.split(marker, 1)[1] if marker in text else ''


def build_consolidation_opportunities(overlay: dict[str, Any], repo: Any) -> list[dict[str, Any]]:
    """Build compact rows plus complete evidence for desktop and web clients."""
    opportunities: list[dict[str, Any]] = []
    for finding in overlay.get('consolidations', []) or []:
        statement_ids = [str(item) for item in finding.get('Statement Internal IDs') or [] if str(item)]
        if not statement_ids and finding.get('Internal ID'):
            statement_ids = [str(finding['Internal ID'])]
        opportunity_type = str(finding.get('Consolidation Type') or 'Other consolidation')
        supported = opportunity_type == 'Group similar statements'
        members = _members(repo, statement_ids)
        opportunities.append(
            {
                'Opportunity ID': _opportunity_id(opportunity_type, statement_ids),
                'Type': opportunity_type,
                'Policies': len({member.get('policy_ocid') or member.get('policy_name') for member in members})
                or len([name for name in str(finding.get('Policy Name(s)') or '').split(',') if name.strip()]),
                'Statements': len(statement_ids) or 1,
                'Scope': finding.get('Compartment') or '',
                'Summary': finding.get('Consolidation Reason') or '',
                'Recommended Action': finding.get('Action') or 'Review opportunity',
                'Statement Internal IDs': statement_ids,
                'Recommended Strategy': 'Group Similar Statements' if supported else '',
                'Handoff Mode': 'supported' if supported else 'advisory',
                'Evidence': {
                    'reason': finding.get('Consolidation Reason') or '',
                    'commonality': _commonality(finding),
                    'members': members,
                    'proposed_statement': _proposed_statement(finding.get('ActionDetail')),
                },
                'checkable': supported,
            }
        )

    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for recommendation in overlay.get('recommendations', []) or []:
        if recommendation.get('Category') != 'Policy Placement':
            continue
        for finding in recommendation.get('Evidence', []) or []:
            if isinstance(finding, dict):
                key = (
                    str(finding.get('Policy OCID') or finding.get('Policy') or ''),
                    str(finding.get('Policy Compartment Path') or ''),
                    str(finding.get('Effective Path') or ''),
                )
                buckets.setdefault(key, []).append(finding)
    for (policy_identity, policy_path, effective_path), findings in buckets.items():
        policy_name = str(findings[0].get('Policy') or policy_identity)
        policy_ocid = str(findings[0].get('Policy OCID') or '')
        statement_ids = [
            str(finding.get('Statement Internal ID') or '')
            for finding in findings
            if finding.get('Statement Internal ID')
        ]
        opportunities.append(
            {
                'Opportunity ID': _opportunity_id('Policy placement', statement_ids),
                'Type': 'Policy placement',
                'Policies': 1,
                'Statements': len(statement_ids),
                'Scope': effective_path,
                'Summary': f'Move {len(statement_ids)} statement(s) from {policy_path or "the source policy scope"} nearer to their effective scope.',
                'Recommended Action': 'Send to Consolidation Workbench',
                'Statement Internal IDs': statement_ids,
                'Recommended Strategy': '',
                'Handoff Mode': 'supported',
                'Evidence': {
                    'reason': 'Effective scope is two or more hierarchy levels below the policy compartment.',
                    'commonality': f'Same source policy ({policy_name}) and effective target ({effective_path}).',
                    'members': [
                        {
                            'internal_id': finding.get('Statement Internal ID') or '',
                            'policy_name': policy_name,
                            'policy_ocid': policy_ocid,
                            'statement_text': finding.get('Statement') or '',
                        }
                        for finding in findings
                    ],
                },
                'checkable': True,
            }
        )
    return opportunities
