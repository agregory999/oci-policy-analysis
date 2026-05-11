"""Service helpers for prospective statement builder metadata and previews."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from oci_policy_analysis.application.core.common.builder_helpers import (
    build_full_statement,
    build_location_clause,
    build_subject_phrase,
    build_tag_variable_and_snippet,
)
from oci_policy_analysis.application.core.common.policy_helpers import calculate_principal_key


@dataclass
class BuilderPreviewResult:
    """Preview payload for web/Tk prospective statement builders."""

    subject_phrase: str
    location_clause: str
    condition_snippet: str
    statement_text: str
    description_suggestion: str
    effective_path: str
    warnings: list[str]


class ProspectiveBuilderService:
    """Builds shared metadata and preview text for prospective statement builders."""

    def __init__(self, policy_repo: Any, reference_repo: Any, simulation_engine: Any):
        self._policy_repo = policy_repo
        self._reference_repo = reference_repo
        self._simulation_engine = simulation_engine

    def get_builder_metadata(self) -> dict[str, Any]:
        principals, principal_details = self._build_principal_choices()
        resources_in_use = self._build_resources_in_use()
        resources_all_possible = self._build_all_resources()
        locations = self._build_locations()

        return {
            'principals': principals,
            'principal_details': {
                key: {'type': ptype, 'domain': domain, 'name': name}
                for key, (ptype, domain, name) in principal_details.items()
            },
            'resources_in_use': resources_in_use,
            'resources_all_possible': resources_all_possible,
            'locations': locations,
            'effective_paths': locations,
            'actions': ['Allow', 'Deny'],
            'verbs': ['inspect', 'read', 'use', 'manage'],
            'where_modes': ['No Where Clause', 'Tag-based Where Clause', 'Other Where Clause'],
            'operators': ['=', '!=', 'IN', 'NOT IN'],
            'access_types': [
                'request.principal.group',
                'request.principal.compartment',
                'target.resource',
                'target.resource.compartment',
            ],
        }

    def build_preview(self, payload: dict[str, Any]) -> BuilderPreviewResult:
        action = str(payload.get('action') or 'Allow').strip() or 'Allow'
        principal_key = str(payload.get('principal_key') or '').strip()
        include_default = bool(payload.get('include_default'))
        verb = str(payload.get('verb') or 'use').strip() or 'use'
        resource = str(payload.get('resource') or '<resource>').strip() or '<resource>'
        location = str(payload.get('location') or 'ROOT').strip() or 'ROOT'
        effective_path = str(payload.get('effective_path') or location).strip() or location
        where_mode = str(payload.get('where_mode') or 'No Where Clause').strip() or 'No Where Clause'

        warnings: list[str] = []
        principals, principal_details = self._build_principal_choices()
        _ = principals
        subject_phrase = self._subject_phrase_for_key(principal_key, principal_details, include_default)

        if where_mode == 'Tag-based Where Clause':
            access_type = str(payload.get('access_type') or '').strip()
            namespace = str(payload.get('namespace') or '').strip()
            tag_key = str(payload.get('tag_key') or '').strip()
            operator = str(payload.get('operator') or '=').strip() or '='
            values = str(payload.get('value') or '').strip()
            _, condition_snippet = build_tag_variable_and_snippet(access_type, namespace, tag_key, operator, values)
        elif where_mode == 'Other Where Clause':
            condition_snippet = str(payload.get('other_where_text') or '').strip()
        else:
            condition_snippet = ''

        location_clause, loc_parts, eff_parts = build_location_clause(location, effective_path)
        if eff_parts[: len(loc_parts)] != loc_parts:
            effective_path = location
            location_clause, loc_parts, eff_parts = build_location_clause(location, effective_path)
            warnings.append('Effective Path was outside Location and has been reset to match Location.')

        statement_text = build_full_statement(
            effect=action,
            subject_phrase=subject_phrase,
            verb=verb,
            resource=resource,
            location_clause=location_clause,
            where_snippet=condition_snippet,
        )

        where_desc = (
            'without where clause'
            if where_mode == 'No Where Clause'
            else ('with custom where clause' if where_mode == 'Other Where Clause' else 'with tag-based where clause')
        )
        description_suggestion = f'{action} {subject_phrase} / {resource} {where_desc}'.strip()

        return BuilderPreviewResult(
            subject_phrase=subject_phrase,
            location_clause=location_clause,
            condition_snippet=condition_snippet,
            statement_text=statement_text,
            description_suggestion=description_suggestion,
            effective_path=effective_path,
            warnings=warnings,
        )

    def _build_locations(self) -> list[str]:
        try:
            engine = self._simulation_engine
            candidates = list(getattr(engine, '_index_compartments', []) or [])
        except Exception:
            candidates = []
        if not candidates:
            try:
                repo_comps = getattr(self._policy_repo, 'compartments', []) or []
                extracted: list[str] = []
                for c in repo_comps:
                    if c is None:
                        continue
                    if isinstance(c, dict):
                        path = str(c.get('hierarchy_path') or '').strip()
                    else:
                        path = str(getattr(c, 'hierarchy_path', '') or '').strip()
                    if path:
                        extracted.append(path)
                candidates = extracted
            except Exception:
                candidates = []
        if not candidates:
            candidates = ['ROOT']
        normalized = {str(c).strip() for c in candidates if str(c).strip()}
        normalized.add('ROOT')
        return sorted(normalized)

    def _build_resources_in_use(self) -> list[str]:
        seen: set[str] = set()
        for stmt in getattr(self._policy_repo, 'regular_statements', []) or []:
            res = str(stmt.get('resource') or '').strip()
            if res:
                seen.add(res)
        return sorted(seen)

    def _build_all_resources(self) -> list[str]:
        data = getattr(self._reference_repo, 'data', {}) or {}
        resources = list((data.get('resources') or {}).keys())
        families = list((data.get('families') or {}).keys())
        return sorted({str(x).strip() for x in resources + families if str(x).strip()})

    def _build_principal_choices(self) -> tuple[list[str], dict[str, tuple[str, str | None, str]]]:
        seen: set[str] = set()
        details: dict[str, tuple[str, str | None, str]] = {}

        for stmt in getattr(self._policy_repo, 'regular_statements', []) or []:
            ptype = str(stmt.get('subject_type') or '').strip()
            subjects = stmt.get('subject') or []
            subj_list = subjects if isinstance(subjects, (list | tuple)) else [subjects]
            for subj in subj_list:
                if not ptype:
                    continue
                if ptype in {'group-id', 'dynamic-group-id'}:
                    name = str(subj or '').strip()
                    if not name:
                        continue
                    key = f'{ptype}:{name}'
                    seen.add(key)
                    details[key] = (ptype, None, name)
                elif ptype == 'service':
                    name = str(subj if isinstance(subj, str) else '').strip()
                    if not name:
                        continue
                    key = calculate_principal_key('service', None, name)
                    seen.add(key)
                    details[key] = ('service', None, name)
                else:
                    if isinstance(subj, (list | tuple)) and len(subj) == 2:
                        domain, name = subj
                    else:
                        domain, name = None, subj
                    name_str = str(name or '').strip()
                    if not name_str:
                        continue
                    domain_val = str(domain).strip() if domain not in (None, '') else None
                    key = calculate_principal_key(ptype, domain_val, name_str)
                    seen.add(key)
                    details[key] = (ptype, domain_val, name_str)

        return sorted(seen), details

    def _subject_phrase_for_key(
        self,
        principal_key: str,
        details: dict[str, tuple[str, str | None, str]],
        include_default: bool,
    ) -> str:
        if not principal_key:
            return '<principal>'
        current = details.get(principal_key)
        if current and current[0] in {'group', 'dynamic-group'}:
            ptype, domain, name = current
            if (domain or '').lower() == 'default' and not include_default:
                override = {**details, principal_key: (ptype, None, name)}
                return build_subject_phrase(principal_key, override)
        return build_subject_phrase(principal_key, details)
