"""Cross-tenancy alias validity and exact duplicate statement findings."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from oci_policy_analysis.application.core.cross_tenancy_corpus import CrossTenancyCorpusBuilder
from oci_policy_analysis.application.core.support.logger import get_logger

LOGGER = get_logger(component='cross_tenancy')


def _norm(value: Any) -> str:
    return re.sub(r'\s+', ' ', str(value or '').strip()).casefold()


def _tuple_text(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple, set)):
        return tuple(sorted(_norm(item) for item in value if _norm(item)))
    return (_norm(value),) if _norm(value) else ()


def _statement_key(statement: dict) -> tuple:
    kind = _norm(statement.get('action_type'))
    is_admit = kind.endswith('admit')
    prefix = 'admit' if is_admit else 'endorse'
    principal_type = _norm(statement.get(f'{prefix}ted_principal_type'))
    principal = _norm(statement.get(f'{prefix}ted_principal'))
    aliases = []
    for alias in set(statement.get('tenancy_aliases') or []):
        resolved = (statement.get('resolved_aliases') or {}).get(alias, {})
        aliases.append(_norm(resolved.get('ocid') or alias))
    if not aliases:
        tenancy_field = 'admitted_tenancy' if is_admit else 'endorse_tenancy'
        tenancy_value = statement.get(tenancy_field) or statement.get('endorsed_principal_tenancy')
        if tenancy_value:
            resolved = (statement.get('resolved_aliases') or {}).get(tenancy_value, {})
            aliases.append(_norm(resolved.get('ocid') or tenancy_value))
    resource = statement.get(f'{prefix}_resource')
    verb = statement.get(f'{prefix}_action')
    permissions = _tuple_text(statement.get(f'{prefix}_permissions'))
    assoc = tuple(
        (_norm(ep.get('resource')), _norm(ep.get('scope')))
        for ep in (statement.get('association') or [])
        if isinstance(ep, dict)
    )
    location = (_norm(statement.get('admit_location_type')), _norm(statement.get('admit_location'))) if is_admit else ()
    return (
        'admit' if is_admit else 'endorse',
        kind,
        principal_type,
        principal,
        tuple(sorted(aliases)),
        _norm(verb),
        _norm(resource),
        permissions,
        location,
        assoc,
        _norm(statement.get('where_clause')),
    )


def _source_reference(statement: dict) -> dict[str, str]:
    """Identify the source row so a UI can show its full parsed details."""
    return {
        'policy_ocid': str(statement.get('policy_ocid') or ''),
        'internal_id': str(statement.get('internal_id') or ''),
        'statement_text': str(statement.get('statement_text') or ''),
        'source_id': str(statement.get('source_id') or ''),
    }


@dataclass(frozen=True)
class CrossTenancyFindingsStrategy:
    """Publish unresolved tenancy references and identical Admit/Endorse statements."""

    strategy_id: str = 'cross_tenancy'
    display_name: str = 'Cross-tenancy validity and duplicates'
    category: str = 'cross_tenancy'
    required_capabilities: frozenset[str] = frozenset()

    def run(self, repo: Any, overlay: dict, params: dict | None = None) -> None:
        corpus = CrossTenancyCorpusBuilder().build(repo)
        statements = corpus.to_dict('statements')
        findings: list[dict] = []
        definitions = corpus.to_dict('definitions')
        alias_types: dict[str, set[str]] = defaultdict(set)
        definitions_by_entity: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for definition in definitions:
            alias = _norm(definition.get('defined_name'))
            kind = _norm(definition.get('defined_type'))
            if alias:
                alias_types[alias].add(kind)
                definitions_by_entity[(kind, alias)].append(definition)

        ambiguous_tenancies: set[str] = set()
        for (kind, alias), group in definitions_by_entity.items():
            ocids = sorted({_norm(item.get('ocid_alias')) for item in group if _norm(item.get('ocid_alias'))})
            if len(ocids) < 2:
                continue
            if kind == 'tenancy':
                ambiguous_tenancies.add(alias)
            findings.append(
                {
                    'Type': 'Ambiguous Define',
                    'Severity': 'Error',
                    'Policy Name': ', '.join(
                        sorted({str(item.get('policy_name') or '') for item in group if item.get('policy_name')})
                    ),
                    'Statement Kind': 'Define',
                    'Alias': str(group[0].get('defined_name') or ''),
                    'Issue': f'{kind} alias resolves to multiple OCIDs: {", ".join(ocids)}',
                    'Statement Text': '\n\n'.join(str(item.get('statement_text') or '') for item in group),
                    'Internal ID': ', '.join(
                        str(item.get('internal_id') or '') for item in group if item.get('internal_id')
                    ),
                    'Statement Count': len(group),
                    'related_statements': [_source_reference(item) for item in group],
                }
            )
        for statement in statements:
            if not isinstance(statement, dict) or not statement.get('parsed', True):
                continue
            aliases = statement.get('tenancy_aliases') or []
            resolution = statement.get('resolved_aliases') or {}
            for alias in aliases:
                if _norm(alias) == 'any-tenancy':
                    continue
                item = resolution.get(alias) or {}
                alias_key = str(alias).casefold()
                resolved = (
                    (
                        bool(item.get('resolved'))
                        or len(
                            {
                                str(d.get('ocid_alias'))
                                for d in definitions
                                if _norm(d.get('defined_name')) == alias_key
                                and _norm(d.get('defined_type')) == 'tenancy'
                                and d.get('ocid_alias')
                            }
                        )
                        == 1
                    )
                    and 'tenancy' in alias_types.get(alias_key, {'tenancy'})
                    and alias_key not in ambiguous_tenancies
                )
                if resolved:
                    continue
                issue = (
                    'Conflicting tenancy defines'
                    if alias_key in ambiguous_tenancies
                    else 'No matching tenancy define'
                    if alias_key not in alias_types
                    else 'Alias is not defined as a tenancy'
                )
                findings.append(
                    {
                        'Type': 'Unresolved Tenancy Define',
                        'Severity': 'Error',
                        'Policy Name': statement.get('policy_name') or '',
                        'Statement Kind': str(statement.get('action_type') or '').title(),
                        'Alias': str(alias),
                        'Issue': issue,
                        'Statement Text': statement.get('statement_text') or '',
                        'Internal ID': statement.get('internal_id') or '',
                        'Statement Count': 1,
                        'related_statements': [_source_reference(statement)],
                    }
                )

        duplicate_groups: dict[tuple, list[dict]] = defaultdict(list)
        for statement in statements:
            if (
                isinstance(statement, dict)
                and statement.get('parsed', True)
                and _norm(statement.get('action_type')) in ('admit', 'deny admit', 'endorse', 'deny endorse')
            ):
                duplicate_groups[_statement_key(statement)].append(statement)
        for key, group in duplicate_groups.items():
            if len(group) < 2:
                continue
            kind = 'Admit' if key[0] == 'admit' else 'Endorse'
            statements_text = [str(st.get('statement_text') or '') for st in group]
            policy_names = sorted({str(st.get('policy_name') or '') for st in group if st.get('policy_name')})
            alias_labels = sorted({str(alias) for st in group for alias in (st.get('tenancy_aliases') or [])})
            findings.append(
                {
                    'Type': f'Duplicate {kind} Statement',
                    'Severity': 'Warning',
                    'Policy Name': ', '.join(policy_names),
                    'Statement Kind': kind,
                    'Alias': ', '.join(alias_labels),
                    'Issue': f'{len(group)} statements have identical parsed scope and conditions',
                    'Statement Text': '\n\n'.join(statements_text),
                    'Internal ID': ', '.join(str(st.get('internal_id') or '') for st in group),
                    'Statement Count': len(group),
                    'related_statements': [_source_reference(st) for st in group],
                }
            )
        findings.sort(key=lambda row: (row['Type'], row['Policy Name'], row['Alias']))
        overlay['cross_tenancy_findings'] = findings
        LOGGER.info(
            'Cross-tenancy findings: total=%d unresolved=%d ambiguous=%d duplicate=%d',
            len(findings),
            sum(row['Type'] == 'Unresolved Tenancy Define' for row in findings),
            sum(row['Type'] == 'Ambiguous Define' for row in findings),
            sum(row['Type'].startswith('Duplicate ') for row in findings),
        )
