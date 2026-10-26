"""Shared cross-tenancy projection adapter for desktop and web consumers."""

from __future__ import annotations

import re
from typing import Any

from oci_policy_analysis.application.core.cross_tenancy_corpus import CrossTenancyCorpus, CrossTenancyCorpusBuilder
from oci_policy_analysis.application.core.cross_tenancy_projection import CrossTenancyProjector


def _conflicting_aliases(definitions: list[dict[str, Any]]) -> set[str]:
    """Find aliases that cannot be merged without changing their meaning."""
    aliases: dict[tuple[str, str], set[str]] = {}
    ambiguous_aliases = set()
    for row in definitions:
        match = re.match(
            r'\s*Define\s+(tenancy|compartment|group|dynamic-group)\s+(\S+)\s+as\s+(\S+)',
            str(row.get('statement_text') or ''),
            re.I,
        )
        kind = str(row.get('defined_type') or (match.group(1) if match else '')).casefold()
        name = str(row.get('defined_name') or (match.group(2) if match else '')).strip('"\'').casefold()
        ocid = str(row.get('ocid_alias') or (match.group(3) if match else '')).strip('"\'')
        if not name:
            continue
        if ocid:
            aliases.setdefault((kind, name), set()).add(ocid)
        if row.get('definition_status') == 'ambiguous':
            ambiguous_aliases.add(name)
    ambiguous_aliases.update(name for (_kind, name), ocids in aliases.items() if len(ocids) > 1)
    return ambiguous_aliases


class CrossTenancyAnalysisService:
    """Project cross-tenancy sources and diagnostics for any consumer.

    Args:
        repo: Repository used when a precompiled corpus is unavailable.
        findings: Optional intelligence findings for a fallback build.
        corpus: Precompiled cross-tenancy snapshot to prefer over a fallback build.

    Attributes:
        repo: Repository used for legacy/fallback projection.
        findings: Findings associated with the fallback repository.
        corpus: Optional snapshot bound to this instance.

    Notes:
        Local relationships do not establish that matching remote policies exist.
        Construct a new service when the active snapshot changes.
    """

    _fallback_aliases = staticmethod(CrossTenancyProjector._fallback_aliases)

    def __init__(
        self,
        repo: Any,
        findings: list[dict] | None = None,
        corpus: CrossTenancyCorpus | None = None,
    ) -> None:
        self.repo = repo
        self.findings = findings or []
        self.corpus = corpus

    def get_analysis_payload(self) -> dict[str, Any]:
        """Return a detached cross-tenancy projection with diagnostics.

        Returns:
            dict[str, Any]: UI-neutral source/relationship projection and schema version.
            Builds a temporary corpus from the repository if no corpus was supplied.
        """
        corpus = self.corpus or CrossTenancyCorpusBuilder().build(self.repo, self.findings)
        return corpus.project()

    @staticmethod
    def generate_single_policy(payload: dict[str, Any]) -> dict[str, Any]:
        """Build an ordered, copy-ready policy from valid and resolved source statements.

        Args:
            payload: Detached projection returned by :meth:`get_analysis_payload`.

        Returns:
            dict[str, Any]: Policy text and counts for included, invalid, unresolved,
            and unclassified source statements. Source policy names and statement
            kinds are retained as OCI policy-language trailing comments.
        """
        included: dict[str, list[dict[str, Any]]] = {'Define': [], 'Admit': [], 'Endorse': []}
        invalid = unresolved = 0
        for kind, key in (
            ('Define', 'defines'),
            ('Admit', 'admit_statements'),
            ('Endorse', 'endorse_statements'),
        ):
            for row in payload.get(key, []) or []:
                if row.get('valid') is not True or row.get('parsed') is False:
                    invalid += 1
                    continue
                if kind == 'Define' and str(row.get('defined_type') or '').casefold() == 'tenancy':
                    if row.get('definition_status') in {'unresolved', 'ambiguous'}:
                        unresolved += 1
                        continue
                if kind in {'Admit', 'Endorse'}:
                    references = row.get('external_tenancies') or []
                    if not references or any(ref.get('status') not in {'resolved', 'special'} for ref in references):
                        unresolved += 1
                        continue
                included[kind].append(row)

        # Aliases are scoped to their source policy. Combining independently
        # valid sources must not make one alias identify several OCI entities.
        # Preserve the source text by excluding those dependencies and relations
        # rather than attempting to rewrite policy-language tokens or literals.
        ambiguous_aliases = _conflicting_aliases(payload.get('defines', []) or [])
        omission_reasons = []
        if ambiguous_aliases:
            for kind, rows in included.items():
                retained = []
                for row in rows:
                    text = str(row.get('statement_text') or '')
                    references = sorted(
                        name
                        for name in ambiguous_aliases
                        if re.search(rf'(?<![\w-]){re.escape(name)}(?![\w-])', text, re.I)
                    )
                    if references:
                        unresolved += 1
                        omission_reasons.append(
                            {
                                'policy_name': row.get('policy_name') or '',
                                'statement_text': text,
                                'reason': 'Conflicting alias definitions: ' + ', '.join(references),
                            }
                        )
                    else:
                        retained.append(row)
                included[kind] = retained

        ordered = []
        for kind in ('Define', 'Admit', 'Endorse'):
            for row in included[kind]:
                statement = str(row.get('statement_text') or '').strip()
                if not statement:
                    invalid += 1
                    continue
                policy_name = ' '.join(str(row.get('policy_name') or 'Unnamed policy').split())
                ordered.append((kind, row, f'{statement} // {kind} · source policy: {policy_name}'))

        # Keep each relation's referenced definitions beside it. Policies are
        # split at the OCI 50-statement limit; definitions may repeat across files.
        definitions = [(kind, row, line) for kind, row, line in ordered if kind == 'Define']
        relations = [(kind, row, line) for kind, row, line in ordered if kind != 'Define']
        bundles = []
        used_definitions = set()
        oversized_relations = set()
        for kind, row, line in relations:
            text = str(row.get('statement_text') or '')
            relevant = []
            relevant_indices = []
            for index, (def_kind, definition, def_line) in enumerate(definitions):
                name = str(definition.get('defined_name') or '').strip()
                if not name:
                    match = re.match(
                        r'\s*Define\s+(?:tenancy|compartment|group|dynamic-group)\s+([^\s]+)',
                        str(definition.get('statement_text') or ''),
                        re.I,
                    )
                    name = match.group(1).strip('"\'') if match else ''
                if name and re.search(rf'(?<![\w-]){re.escape(name)}(?![\w-])', text, re.I):
                    relevant.append((def_kind, definition, def_line))
                    relevant_indices.append(index)
            if len(relevant) >= 50:
                oversized_relations.add(id(row))
                unresolved += 1
                omission_reasons.append(
                    {
                        'policy_name': row.get('policy_name') or '',
                        'statement_text': text,
                        'reason': 'Statement and required definitions exceed the 50-statement policy limit.',
                    }
                )
                continue
            used_definitions.update(relevant_indices)
            bundles.append([*relevant, (kind, row, line)])
        ordered = [item for item in ordered if id(item[1]) not in oversized_relations]
        included = {
            kind: [row for row in rows if id(row) not in oversized_relations] for kind, rows in included.items()
        }
        standalone = [[item] for index, item in enumerate(definitions) if index not in used_definitions]
        bundles = [*standalone, *bundles]
        if not relations:
            bundles = [[item] for item in definitions]

        policy_lines = []
        current = []
        for bundle in bundles:
            complete_bundle = bundle
            present = {item[2] for item in current if item[0] == 'Define'}
            bundle = [item for item in bundle if item[0] != 'Define' or item[2] not in present]
            if current and len(current) + len(bundle) > 50:
                policy_lines.append([item[2] for item in current])
                current = []
                # Definitions from the previous policy are not in scope in the
                # new policy, so restore every dependency before packing it.
                bundle = complete_bundle
            current.extend(bundle)
        if current:
            policy_lines.append([item[2] for item in current])
        policies = [
            {'name': f'CrossTenancy-{index:02d}', 'text': '\n'.join(lines), 'included': len(lines)}
            for index, lines in enumerate(policy_lines, 1)
        ]
        lines = [line for _kind, _row, line in ordered]
        omission_comments = [
            '// Not included: '
            + ' | '.join(
                ' '.join(str(row.get(field) or '').split()) for field in ('policy_name', 'reason', 'statement_text')
            )
            for row in omission_reasons
        ]
        comments = '\n\n' + '\n'.join(omission_comments) if omission_comments else ''
        for policy in policies:
            policy['text'] += comments
        unclassified = len(payload.get('unknown_statements', []) or [])
        return {
            'text': '\n'.join([*lines, *omission_comments]),
            'policies': policies,
            'included': len(lines),
            'included_by_kind': {
                kind: sum(bool(str(row.get('statement_text') or '').strip()) for row in rows)
                for kind, rows in included.items()
            },
            'invalid_or_unparsed': invalid,
            'unresolved_or_ambiguous': unresolved,
            'omission_reasons': omission_reasons,
            'unclassified': unclassified,
        }
