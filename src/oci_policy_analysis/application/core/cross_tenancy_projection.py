"""Shared interpretation and presentation data for cross-tenancy policies."""

from __future__ import annotations

import hashlib
import re
from typing import Any


def _text(value: Any) -> str:
    return str(value or '').strip()


def _stable_key(policy_ocid: str, statement_text: str) -> str:
    normalized = re.sub(r'\s+', ' ', statement_text.strip()).casefold()
    return hashlib.sha256(f'{policy_ocid}|{normalized}'.encode()).hexdigest()


class CrossTenancyProjector:
    """Build a normalized, UI-neutral model of tenancy links and cross-tenancy statements."""

    def __init__(self, repo: Any, findings: list[dict] | None = None) -> None:
        self.repo = repo
        self.findings = findings or []

    def get_analysis_payload(self) -> dict[str, Any]:
        repo = self.repo
        local = {
            'name': _text(getattr(repo, 'tenancy_name', '')) or 'This tenancy',
            'ocid': _text(getattr(repo, 'tenancy_ocid', '')),
            'role': 'Local tenancy',
        }
        defines = [dict(item) for item in (getattr(repo, 'defined_aliases', []) or []) if isinstance(item, dict)]
        statements = [
            dict(item) for item in (getattr(repo, 'cross_tenancy_statements', []) or []) if isinstance(item, dict)
        ]
        tenancy_ocids: dict[str, set[str]] = {}
        for item in defines:
            if _text(item.get('defined_type')).casefold() == 'tenancy' and _text(item.get('defined_name')):
                tenancy_ocids.setdefault(_text(item['defined_name']).casefold(), set()).add(
                    _text(item.get('ocid_alias'))
                )
        alias_to_ocid = {alias: next(iter(ocids)) for alias, ocids in tenancy_ocids.items() if len(ocids) == 1}
        ambiguous_tenancies = {alias for alias, ocids in tenancy_ocids.items() if len(ocids - {''}) > 1}
        referenced: dict[str, set[str]] = {key: set() for key in alias_to_ocid}
        alias_roles: dict[str, set[str]] = {}
        admit_rows, endorse_rows, unknown_rows = [], [], []

        for item in statements:
            text = _text(item.get('statement_text'))
            text_cf = text.casefold()
            kind = (
                'Admit'
                if text_cf.startswith(('admit', 'deny admit'))
                else 'Endorse'
                if text_cf.startswith(('endorse', 'deny endorse'))
                else 'Unknown'
            )
            aliases = [_text(a) for a in (item.get('tenancy_aliases') or []) if _text(a)]
            if not aliases:
                aliases = self._fallback_aliases(item, kind)
            if re.search(r'\bany-tenancy\b', text, re.I) and not any(
                alias.casefold() == 'any-tenancy' for alias in aliases
            ):
                aliases.append('any-tenancy')
            aliases = list(dict.fromkeys(aliases))
            stable_key = _text(item.get('source_id')) or _stable_key(_text(item.get('policy_ocid')), text)
            for alias in aliases:
                referenced.setdefault(alias.casefold(), set()).add(stable_key)
                role = (
                    'Participant'
                    if item.get('association')
                    else 'Source'
                    if kind == 'Admit'
                    else 'Target'
                    if kind == 'Endorse'
                    else 'Participant'
                )
                alias_roles.setdefault(alias.casefold(), set()).add(role)

            resolved = item.get('resolved_aliases') or {}
            external = []
            for alias in aliases:
                special = alias.casefold() == 'any-tenancy'
                result = resolved.get(alias, {}) if isinstance(resolved, dict) else {}
                ocid = _text(result.get('ocid')) if isinstance(result, dict) else ''
                ocid = (
                    ''
                    if special or alias.casefold() in ambiguous_tenancies
                    else ocid or alias_to_ocid.get(alias.casefold(), '')
                )
                external.append(
                    {
                        'alias': alias,
                        'ocid': ocid,
                        'resolved': bool(ocid),
                        'special': special,
                        'status': 'special'
                        if special
                        else 'ambiguous'
                        if alias.casefold() in ambiguous_tenancies
                        else 'resolved'
                        if ocid
                        else 'unresolved',
                    }
                )
            direction = self._direction(kind, local, external, item)
            principal_identity = None
            if kind in {'Admit', 'Endorse'}:
                principal_type = _text(
                    item.get('admitted_principal_type' if kind == 'Admit' else 'endorsed_principal_type')
                )
                principal_name = _text(item.get('admitted_principal' if kind == 'Admit' else 'endorsed_principal'))
                if principal_type or principal_name:
                    if kind == 'Admit':
                        tenancy_alias = _text(item.get('admitted_tenancy') or item.get('admitted_principal_tenancy'))
                        tenancy = next(
                            (entry for entry in external if entry['alias'].casefold() == tenancy_alias.casefold()), None
                        )
                        principal_identity = {
                            'type': principal_type,
                            'name': principal_name,
                            'tenancy_alias': tenancy_alias,
                            'tenancy_ocid': tenancy['ocid'] if tenancy else '',
                            'tenancy_status': tenancy['status'] if tenancy else 'unresolved',
                        }
                    else:
                        principal_identity = {
                            'type': principal_type,
                            'name': principal_name,
                            'tenancy_alias': 'local',
                            'tenancy_ocid': local['ocid'],
                            'tenancy_status': 'local',
                        }
            row = {
                **item,
                'kind': kind,
                'stable_key': stable_key,
                'parsed_fields': {
                    str(key): value
                    for key, value in item.items()
                    if key not in {'policy_name', 'policy_ocid', 'statement_text', 'creation_time', 'parsed'}
                },
                'external_tenancies': external,
                'direction': direction,
                'participants': self._participants(local, kind, external, item),
                'reciprocal_guidance': self._reciprocal_guidance(kind, item),
            }
            if principal_identity:
                row['principal_identity'] = principal_identity
            if kind == 'Admit':
                admit_rows.append(row)
            elif kind == 'Endorse':
                endorse_rows.append(row)
            else:
                unknown_rows.append(row)

        define_rows = []
        entity_ocids: dict[tuple[str, str], set[str]] = {}
        for item in defines:
            entity_ocids.setdefault(
                (_text(item.get('defined_type')).casefold(), _text(item.get('defined_name')).casefold()), set()
            ).add(_text(item.get('ocid_alias')))
        for item in defines:
            alias = _text(item.get('defined_name'))
            refs = referenced.get(alias.casefold(), set())
            definition_ocids = entity_ocids.get(
                (_text(item.get('defined_type')).casefold(), alias.casefold()), set()
            ) - {''}
            define_rows.append(
                {
                    **item,
                    'kind': 'Define',
                    'stable_key': _text(item.get('source_id'))
                    or _stable_key(_text(item.get('policy_ocid')), _text(item.get('statement_text'))),
                    'reference_count': len(refs),
                    'reference_status': 'Referenced' if refs else 'Unused define',
                    'definition_status': 'ambiguous'
                    if len(definition_ocids) > 1
                    else 'resolved'
                    if definition_ocids
                    else 'unresolved',
                    'relationship_role': ' / '.join(sorted(alias_roles.get(alias.casefold(), set()))) or 'Unreferenced',
                    'local_ocid_match': bool(
                        _text(item.get('ocid_alias')) and _text(item.get('ocid_alias')) == local['ocid']
                    ),
                }
            )

        relationship_graph = self._relationship_graph(define_rows, admit_rows + endorse_rows + unknown_rows)
        for row in define_rows:
            alias = _text(row.get('defined_name'))
            kind = _text(row.get('defined_type')).casefold()
            key = _text(row.get('stable_key'))
            if kind == 'tenancy':
                associated = [
                    {'name': node['alias'], 'basis': 'Explicit tenancy define'}
                    for node in relationship_graph['tenancies']
                    if node['alias'].casefold() == alias.casefold()
                    and any(link['alias'].casefold() == alias.casefold() for link in relationship_graph['links'])
                ]
            else:
                associated = [
                    {
                        'name': local['name'] if node['tenancy_alias'] == 'local' else node['tenancy_alias'],
                        'basis': node.get('ownership_basis') or 'Deduced from cross-tenancy statements',
                        'source_ids': [source_id for source_id in node['statement_keys'] if source_id != key],
                    }
                    for node in relationship_graph['subnodes']
                    if node['defined']
                    and node['tenancy_alias']
                    and key in node['statement_keys']
                    and node['kind'] == kind
                    and node['name'].casefold() == alias.casefold()
                ]
            row['tenancy_associations'] = list({item['name'].casefold(): item for item in associated}.values())

        return {
            'local_tenancy': local,
            'relationship_graph': relationship_graph,
            'defines': define_rows,
            'admit_statements': admit_rows,
            'endorse_statements': endorse_rows,
            'unknown_statements': unknown_rows,
            'findings': [dict(row) for row in self.findings],
            # Compatibility keys used by the first web page implementation.
            'admit_statements_basic': admit_rows,
            'endorse_statements_basic': endorse_rows,
            'unknown_statements_basic': unknown_rows,
            'counts': {
                'defines': len(define_rows),
                'admit': len(admit_rows),
                'endorse': len(endorse_rows),
                'unknown': len(unknown_rows),
                'findings': len(self.findings),
                'unresolved': sum(1 for f in self.findings if 'Unresolved' in _text(f.get('Type'))),
                'duplicates': sum(1 for f in self.findings if 'Duplicate' in _text(f.get('Type'))),
                'ambiguous': sum(1 for f in self.findings if 'Ambiguous' in _text(f.get('Type'))),
            },
        }

    @staticmethod
    def _relationship_graph(defines: list[dict], statements: list[dict]) -> dict[str, list[dict]]:
        """Return stable, UI-neutral graph nodes and links from parsed aliases."""
        tenancies: dict[str, dict] = {}
        links: dict[tuple[str, str, bool], set[str]] = {}
        for row in statements:
            key = _text(row.get('stable_key'))
            association = bool(row.get('association'))
            directions = (
                ('incoming', 'outgoing')
                if association
                else (
                    ('incoming',)
                    if row.get('kind') == 'Admit'
                    else ('outgoing',)
                    if row.get('kind') == 'Endorse'
                    else ()
                )
            )
            for external in row.get('external_tenancies') or []:
                alias = _text(external.get('alias'))
                if not alias:
                    continue
                alias_key = alias.casefold()
                node = tenancies.setdefault(
                    alias_key,
                    {
                        'id': f'tenancy:{alias_key}',
                        'alias': alias,
                        'ocid': '',
                        'resolved': False,
                        'special': bool(external.get('special')),
                        'statement_keys': set(),
                        'incoming_count': 0,
                        'outgoing_count': 0,
                        'association_count': 0,
                    },
                )
                node['ocid'] = node['ocid'] or _text(external.get('ocid'))
                node['resolved'] = bool(node['ocid'])
                node['special'] = bool(node['special'] or external.get('special'))
                node['statement_keys'].add(key)
                if association:
                    node['association_count'] += 1
                elif row.get('kind') == 'Admit':
                    node['incoming_count'] += 1
                elif row.get('kind') == 'Endorse':
                    node['outgoing_count'] += 1
                for direction in directions:
                    links.setdefault((alias_key, direction, association), set()).add(key)

        graph_links = [
            {
                'id': f'link:{alias_key}:{direction}:{int(association)}',
                'alias': tenancies[alias_key]['alias'],
                'direction': direction,
                'association': association,
                'statement_keys': sorted(keys),
                'count': len(keys),
            }
            for (alias_key, direction, association), keys in sorted(links.items())
        ]

        defined_entities = []
        subnodes: dict[tuple[str, str, str], dict] = {}

        def add_subnode(
            kind: str,
            name: str,
            owner: str,
            key: str,
            definition_key: str = '',
            basis: str = 'unknown',
        ) -> None:
            kind, name, owner = _text(kind).casefold(), _text(name), _text(owner)
            if not kind or not name:
                return
            node = subnodes.setdefault(
                (owner.casefold(), kind, name.casefold()),
                {
                    'id': f'entity:{owner.casefold()}:{kind}:{name.casefold()}',
                    'kind': kind,
                    'name': name,
                    'tenancy_alias': owner,
                    'ownership_basis': basis,
                    'statement_keys': set(),
                    'defined': False,
                },
            )
            node['statement_keys'].add(key)
            if basis != 'unknown':
                node['ownership_basis'] = basis
            if definition_key:
                node['statement_keys'].add(definition_key)
                node['defined'] = True

        # Explicit scope is stronger than the direction of a statement: an
        # Endorse can name a remote compartment while its principal is local.
        ownership: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for row in statements:
            statement_text = _text(row.get('statement_text'))
            key = _text(row.get('stable_key'))
            explicit_principals: set[tuple[str, str]] = set()
            for match in re.finditer(
                r'\b(dynamic-group|group|compartment|any-user)\s+([^\s,{}]+)\s+of\s+tenancy\s+([^\s,{}]+)',
                statement_text,
                re.I,
            ):
                kind, name, owner = (part.strip('\'"') for part in match.groups())
                if kind.casefold() == 'any-user':
                    name = 'any-user'
                ownership.setdefault((kind.casefold(), name.casefold()), []).append((owner, key))
                add_subnode(kind, name, owner, key, basis='explicit of tenancy clause')
                explicit_principals.add((kind.casefold(), owner.casefold()))
            if row.get('kind') == 'Admit':
                kind = _text(row.get('admitted_principal_type')).casefold()
                name = _text(row.get('admitted_principal'))
                owner = _text(row.get('admitted_tenancy'))
                if (
                    kind in {'group', 'dynamic-group', 'any-user'}
                    and owner
                    and (kind, owner.casefold()) not in explicit_principals
                ):
                    name = 'any-user' if kind == 'any-user' else name
                    add_subnode(kind, name, owner, key, basis='parsed admitted principal')
                    ownership.setdefault((kind, name.casefold()), []).append((owner, key))
            elif row.get('kind') == 'Endorse':
                kind = _text(row.get('endorsed_principal_type')).casefold()
                name = _text(row.get('endorsed_principal'))
                if kind in {'group', 'dynamic-group', 'any-user'} and name:
                    name = 'any-user' if kind == 'any-user' else name
                    add_subnode(kind, name, 'local', key, basis='parsed endorsed principal')
                    ownership.setdefault((kind, name.casefold()), []).append(('local', key))

        for row in defines:
            alias = _text(row.get('defined_name'))
            alias_key = alias.casefold()
            linked = {
                _text(statement.get('stable_key'))
                for statement in statements
                if alias
                and re.search(rf'(?<![\w-]){re.escape(alias)}(?![\w-])', _text(statement.get('statement_text')), re.I)
            }
            definition_key = _text(row.get('stable_key'))
            linked.add(definition_key)
            if _text(row.get('defined_type')).casefold() == 'tenancy' and alias_key in tenancies:
                tenancies[alias_key]['statement_keys'].update(linked)
                continue
            kind = _text(row.get('defined_type')).casefold()
            matches = ownership.get((kind, alias_key), [])
            for owner, key in matches:
                add_subnode(kind, alias, owner, key, definition_key)
            # Referenced definitions without an explicit owner remain in the
            # graph, but we do not guess which tenancy owns them.
            if len(linked) > 1 and not matches:
                for key in linked - {definition_key}:
                    add_subnode(kind, alias, '', key, definition_key)
            defined_entities.append(
                {
                    'id': f'definition:{definition_key}',
                    'defined_type': _text(row.get('defined_type')) or 'entity',
                    'defined_name': alias,
                    'ocid_alias': _text(row.get('ocid_alias')),
                    'reference_count': len(linked) - 1,
                    'statement_keys': sorted(linked),
                    'orphan': len(linked) == 1,
                }
            )

        graph_tenancies = [
            {**node, 'statement_keys': sorted(node['statement_keys'])} for _, node in sorted(tenancies.items())
        ]
        graph_subnodes = [
            {**node, 'statement_keys': sorted(node['statement_keys'])} for _, node in sorted(subnodes.items())
        ]
        return {
            'tenancies': graph_tenancies,
            'links': graph_links,
            'defined_entities': defined_entities,
            'subnodes': graph_subnodes,
        }

    @staticmethod
    def _fallback_aliases(statement: dict, kind: str) -> list[str]:
        keys = (
            ('admitted_tenancy', 'admit_associate_tenancy', 'admit_associate_with_tenancy')
            if kind == 'Admit'
            else (
                'endorse_tenancy',
                'endorsed_principal_tenancy',
                'endorse_associate_tenancy',
                'endorse_associate_with_tenancy',
            )
        )
        values = [_text(statement.get(key)) for key in keys]
        values.extend(_text(ep.get('scope')) for ep in (statement.get('association') or []) if isinstance(ep, dict))
        aliases = []
        for value in values:
            lowered = value.casefold()
            if not value or lowered.startswith('compartment ') or lowered in {'any-tenancy', 'any tenancy'}:
                continue
            if lowered.startswith('tenancy '):
                value = value.split(None, 1)[1]
            aliases.append(value)
        return list(dict.fromkeys(aliases))

    @staticmethod
    def _direction(kind: str, local: dict, external: list[dict], statement: dict) -> str:
        if statement.get('association'):
            return 'Association participants: principal tenancy plus both resource endpoints; validate each scope'
        if kind == 'Admit':
            return f'{", ".join(item["alias"] for item in external) or "Unknown remote tenancy"} → {local["name"]} (resource tenancy)'
        if kind == 'Endorse':
            return f'{local["name"]} (principal tenancy) → {", ".join(item["alias"] for item in external) or "Unknown remote tenancy"}'
        if statement.get('association'):
            return 'Association participants; endpoint tenancy roles require review'
        return 'Direction not inferred'

    @staticmethod
    def _participants(local: dict, kind: str, external: list[dict], statement: dict) -> list[dict]:
        participants = [{'name': local['name'], 'ocid': local['ocid'], 'role': 'Local tenancy'}]
        default_role = (
            'Source tenancy' if kind == 'Admit' else 'Target tenancy' if kind == 'Endorse' else 'Referenced tenancy'
        )
        participants.extend({**item, 'name': item['alias'], 'role': default_role} for item in external)
        endpoints = statement.get('association') or []
        for idx, endpoint in enumerate(endpoints, start=1):
            if not isinstance(endpoint, dict):
                continue
            scope = _text(endpoint.get('scope'))
            if scope:
                participants.append(
                    {
                        'name': scope,
                        'ocid': '',
                        'role': f'Association endpoint {idx}',
                        'resource': _text(endpoint.get('resource')),
                    }
                )
        return participants

    @staticmethod
    def _reciprocal_guidance(kind: str, statement: dict) -> str:
        if not statement.get('parsed'):
            return 'Statement is not fully parsed; review manually before drafting a reciprocal policy.'
        if statement.get('association'):
            return 'Review all participating tenancy scopes; an association can involve the local tenancy and multiple referenced tenancies.'
        if kind == 'Admit':
            return 'Check the remote tenancy for a matching Endorse statement covering this principal, action, and resource.'
        if kind == 'Endorse':
            return 'Check this tenancy for a matching Admit statement covering this principal, action, and resource.'
        return 'Review all participating tenancy scopes; an association can involve the local tenancy and multiple referenced tenancies.'
