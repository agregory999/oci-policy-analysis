"""Versioned, immutable snapshot of cross-tenancy source facts and their projection."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from oci_policy_analysis.application.core.common.policy_helpers import canonicalize_principal_key
from oci_policy_analysis.application.core.support.logger import get_logger

LOGGER = get_logger(component='core.cross_tenancy_corpus')


def _source_id(kind: str, row: dict, position: int, used: set[str]) -> str:
    """Prefer a unique parser ID and fall back to a deterministic source occurrence."""
    internal = str(row.get('internal_id') or '').strip()
    base = f'ct:{kind}:{internal}' if internal else ''
    if not base or base in used:
        normalized = re.sub(r'\s+', ' ', str(row.get('statement_text') or '').strip()).casefold()
        digest = hashlib.sha256(f'{row.get("policy_ocid") or ""}|{kind}|{normalized}|{position}'.encode()).hexdigest()[
            :20
        ]
        base = f'ct:{kind}:{digest}'
    used.add(base)
    return base


@dataclass(frozen=True)
class CrossTenancyCorpus:
    """A snapshot; serialized records are isolated from mutable repository data."""

    schema_version: int
    local_tenancy_json: str
    definitions_json: tuple[str, ...]
    statements_json: tuple[str, ...]
    relationships_json: tuple[str, ...]
    findings_json: tuple[str, ...]
    diagnostics_json: tuple[str, ...]
    projection_json: str

    def to_dict(self, section: str | None = None) -> dict[str, Any] | list[Any]:
        def read(name: str) -> dict[str, Any] | list[Any]:
            if name == 'summary':
                return self.summary()
            if name == 'local_tenancy':
                return json.loads(self.local_tenancy_json)
            values = getattr(self, f'{name}_json')
            return [json.loads(value) for value in values]

        names = ('summary', 'local_tenancy', 'definitions', 'statements', 'relationships', 'findings', 'diagnostics')
        if section and section != 'All':
            return read(section) if section in names else {'error': f'Unknown corpus section: {section}'}
        return {'schema_version': self.schema_version, **{name: read(name) for name in names}}

    def summary(self) -> dict[str, int]:
        return {
            'definitions': len(self.definitions_json),
            'statements': len(self.statements_json),
            'relationships': len(self.relationships_json),
            'findings': len(self.findings_json),
            'diagnostics': len(self.diagnostics_json),
        }

    def project(self) -> dict[str, Any]:
        """Return a detached UI-neutral projection shared by desktop and web."""
        payload = json.loads(self.projection_json)
        payload['schema_version'] = self.schema_version
        return payload


class CrossTenancyCorpusBuilder:
    """Capture all CT source occurrences and their resolved display relationships."""

    @staticmethod
    def _restore_legacy_association(row: dict) -> None:
        """Reconstruct association endpoints absent or incomplete in older caches."""
        text = str(row.get('statement_text') or '')
        match = re.match(r'^\s*(?:deny\s+)?(admit|endorse)\b', text, re.IGNORECASE)
        if not match or not re.search(r'\bto\s+associate\b', text, re.IGNORECASE):
            return
        from oci_policy_analysis.application.core.parser.policy_statement_normalizer import PolicyStatementNormalizer

        normalized = PolicyStatementNormalizer().normalize(text, match.group(1), row)
        if not normalized.get('parsed') or not normalized.get('association'):
            return
        for key, value in normalized.items():
            if key.startswith(('admit', 'endorse')) or key in ('association', 'tenancy_aliases', 'principal_keys'):
                row[key] = value

    def build(self, repo: Any, findings: list[dict] | None = None) -> CrossTenancyCorpus:
        from oci_policy_analysis.application.core.cross_tenancy_projection import CrossTenancyProjector

        used: set[str] = set()
        definitions = []
        statements = []
        for kind, source, target in (
            ('define', getattr(repo, 'defined_aliases', []) or [], definitions),
            ('statement', getattr(repo, 'cross_tenancy_statements', []) or [], statements),
        ):
            for position, item in enumerate(source):
                if not isinstance(item, dict):
                    continue
                row = copy.deepcopy(item)
                if kind == 'statement' and (
                    not row.get('association')
                    or any(
                        not endpoint.get('scope')
                        for endpoint in row.get('association', [])
                        if isinstance(endpoint, dict)
                    )
                ):
                    self._restore_legacy_association(row)
                if isinstance(row.get('principal_keys'), list):
                    row['principal_keys'] = list(
                        dict.fromkeys(canonicalize_principal_key(key) for key in row['principal_keys'])
                    )
                row['source_id'] = _source_id(kind, row, position, used)
                row['source_position'] = position
                target.append(row)

        class Snapshot:
            pass

        snapshot = Snapshot()
        snapshot.tenancy_name = getattr(repo, 'tenancy_name', '')
        snapshot.tenancy_ocid = getattr(repo, 'tenancy_ocid', '')
        snapshot.defined_aliases = definitions
        snapshot.cross_tenancy_statements = statements
        enriched_findings = copy.deepcopy(findings or [])
        sources = definitions + statements
        for finding in enriched_findings:
            matched: set[str] = set()
            source_ids = []
            for reference in finding.get('related_statements') or []:
                source = next(
                    (
                        row
                        for row in sources
                        if row['source_id'] not in matched
                        and str(row.get('internal_id') or '') == str(reference.get('internal_id') or '')
                        and str(row.get('policy_ocid') or '') == str(reference.get('policy_ocid') or '')
                        and str(row.get('statement_text') or '') == str(reference.get('statement_text') or '')
                    ),
                    None,
                )
                if source:
                    reference['source_id'] = source['source_id']
                    source_ids.append(source['source_id'])
                    matched.add(source['source_id'])
            finding['source_ids'] = source_ids
        payload = CrossTenancyProjector(snapshot, enriched_findings).get_analysis_payload()
        graph = payload['relationship_graph']
        projected_definitions = {row['source_id']: row for row in payload['defines']}
        projected_statements = {
            row['source_id']: row
            for row in (payload['admit_statements'] + payload['endorse_statements'] + payload['unknown_statements'])
        }
        for row in definitions:
            projected = projected_definitions[row['source_id']]
            row['definition_status'] = projected['definition_status']
            row['reference_source_ids'] = sorted(
                {
                    key
                    for entity in graph['defined_entities']
                    if entity['defined_name'].casefold() == str(row.get('defined_name') or '').casefold()
                    and entity['defined_type'].casefold() == str(row.get('defined_type') or '').casefold()
                    for key in entity['statement_keys']
                    if key != row['source_id']
                }
            )
            row['inferred_owners'] = projected.get('tenancy_associations', [])
        for row in statements:
            projected = projected_statements[row['source_id']]
            row['kind'] = projected['kind']
            row['tenancy_references'] = projected['external_tenancies']
            if projected.get('principal_identity'):
                row['principal_identity'] = projected['principal_identity']
            row['relationship_ids'] = [
                link['id'] for link in graph['links'] if row['source_id'] in link['statement_keys']
            ]
        diagnostics = [
            {
                'type': 'parse_uncertainty',
                'source_id': row['source_id'],
                'message': 'Statement was not fully parsed; relationship details may be incomplete.',
            }
            for row in statements
            if row.get('parsed') is False
        ]
        diagnostics.extend(
            {
                'type': 'unplaced_entity',
                'source_ids': node['statement_keys'],
                'entity': f'{node["kind"]} {node["name"]}',
                'message': 'Referenced entity has no provable tenancy owner.',
            }
            for node in graph['subnodes']
            if not node['tenancy_alias']
        )
        relationships = [
            {
                'id': link['id'],
                'alias': link['alias'],
                'direction': link['direction'],
                'association': link['association'],
                'source_ids': link['statement_keys'],
            }
            for link in graph['links']
        ]
        corpus = CrossTenancyCorpus(
            schema_version=1,
            local_tenancy_json=json.dumps(payload['local_tenancy'], default=str),
            definitions_json=tuple(json.dumps(row, default=str) for row in definitions),
            statements_json=tuple(json.dumps(row, default=str) for row in statements),
            relationships_json=tuple(json.dumps(row, default=str) for row in relationships),
            findings_json=tuple(json.dumps(row, default=str) for row in payload['findings']),
            diagnostics_json=tuple(json.dumps(row, default=str) for row in diagnostics),
            projection_json=json.dumps(payload, default=str),
        )
        statuses = {
            status: sum(
                ref.get('status') == status
                for row in payload['admit_statements'] + payload['endorse_statements'] + payload['unknown_statements']
                for ref in row.get('external_tenancies', [])
            )
            for status in ('resolved', 'unresolved', 'ambiguous', 'special')
        }
        LOGGER.info(
            'Cross-tenancy corpus built: definitions=%d statements=%d relationships=%d '
            'findings=%d diagnostics=%d references=%s',
            len(definitions),
            len(statements),
            len(relationships),
            len(enriched_findings),
            len(diagnostics),
            statuses,
        )
        return corpus
