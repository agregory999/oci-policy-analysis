"""Shared tag-based policy query helpers."""

from __future__ import annotations

from collections import Counter
from typing import Any

from oci_policy_analysis.application.core.models.models import PolicySearch, RegularPolicyStatement
from oci_policy_analysis.application.core.parser import collect_tag_conditions
from oci_policy_analysis.application.core.support.logger import get_logger

LOGGER = get_logger(component='tag_based_policy_service')

TAG_FILTER_FIELDS = {
    'tag_access_type',
    'tag_access_semantics',
    'tag_namespace',
    'tag_key',
    'tag_value',
    'tag_operator',
}

POLICY_TAG_FILTER_FIELDS = {'policy_tag', 'policy_defined_tag', 'policy_freeform_tag'}


class TagBasedPolicyService:
    """Centralized parsed-condition support for tag-based policy queries."""

    SEMANTICS_BY_ACCESS_TYPE = {
        'request.principal.group': 'requestor_group_tag',
        'request.principal.compartment': 'requestor_compartment_tag',
        'target.resource': 'target_resource_tag',
        'target.resource.compartment': 'target_compartment_tag',
    }

    TARGET_RESOURCE_WARNINGS = (
        'target.resource.tag conditions may require a separate list or inspect policy to discover tagged resources.',
        'target.resource.tag conditions cannot grant create permissions because the target resource tag does not exist yet.',
        'target.resource.tag support has service-specific limitations; verify the target service documents tag conditions.',
    )
    TARGET_COMPARTMENT_WARNINGS = (
        'target.resource.compartment.tag applies through nested compartments, so child compartment resources can match parent compartment tags.',
    )

    @classmethod
    def enrich_statement(cls, statement: RegularPolicyStatement) -> RegularPolicyStatement:
        """Attach normalized tag-condition and warning fields to a statement."""

        conditions = str(statement.get('conditions') or '').strip()
        existing = statement.get('tag_conditions')
        if isinstance(existing, list):
            tag_conditions = [dict(item) for item in existing if isinstance(item, dict)]
        else:
            tag_conditions = []
            if conditions:
                try:
                    _structure, collected = collect_tag_conditions(conditions)
                    for cond in collected:
                        value = getattr(cond, 'value', '')
                        tag_conditions.append(
                            {
                                'condition_id': getattr(cond, 'condition_id', ''),
                                'access_type': getattr(cond, 'access_type', ''),
                                'tag_namespace': getattr(cond, 'tag_namespace', ''),
                                'tag_key': getattr(cond, 'tag_key', ''),
                                'operator': getattr(cond, 'operator', ''),
                                'value': value,
                                'value_type': cls._infer_value_type(value),
                                'right_kind': cls._infer_right_kind(value),
                                'subexpression': getattr(cond, 'subexpression', ''),
                                'access_semantics': cls.SEMANTICS_BY_ACCESS_TYPE.get(
                                    getattr(cond, 'access_type', ''), ''
                                ),
                            }
                        )
                except Exception:
                    LOGGER.debug('Failed to collect tag conditions for statement', exc_info=True)
        statement['tag_conditions'] = tag_conditions
        statement['tag_context_warnings'] = cls.context_warnings_for_conditions(tag_conditions)
        return statement

    @classmethod
    def enrich_statements(cls, statements: list[RegularPolicyStatement]) -> list[RegularPolicyStatement]:
        for statement in statements or []:
            if isinstance(statement, dict):
                cls.enrich_statement(statement)
        return statements

    @classmethod
    def matches_tag_filters(cls, statement: RegularPolicyStatement, filters: PolicySearch) -> bool:
        """Return true when one parsed tag condition satisfies all supplied tag filters."""

        active = {field: cls._as_terms(filters.get(field)) for field in TAG_FILTER_FIELDS if filters.get(field)}
        if not active:
            return True

        cls.enrich_statement(statement)
        tag_conditions = statement.get('tag_conditions')
        if isinstance(tag_conditions, list):
            for condition in tag_conditions:
                if not isinstance(condition, dict):
                    continue
                if all(cls._condition_field_matches(condition, field, terms) for field, terms in active.items()):
                    return True

        # Degraded fallback for old rows where parser enrichment is absent or failed.
        conditions_text = str(statement.get('conditions') or '').casefold()
        if not tag_conditions and '.tag.' in conditions_text:
            return all(any(term.casefold() in conditions_text for term in terms) for terms in active.values())
        return False

    @classmethod
    def matches_condition_atom_terms(cls, statement: RegularPolicyStatement, terms_value: object) -> bool:
        terms = cls._as_terms(terms_value)
        if not terms:
            return True
        atoms = statement.get('condition_atoms')
        if not isinstance(atoms, list):
            structure = statement.get('where_clause_structure') or statement.get('where_clause') or {}
            atoms = structure.get('atoms', []) if isinstance(structure, dict) else []
        haystacks: list[str] = []
        for atom in atoms if isinstance(atoms, list) else []:
            if not isinstance(atom, dict):
                continue
            haystacks.extend(
                str(atom.get(field) or '')
                for field in (
                    'left',
                    'normalized_left',
                    'right',
                    'operator',
                    'value_type',
                    'evidence_kind',
                    'subexpression',
                )
            )
        combined = ' '.join(haystacks).casefold()
        return any(term.casefold() in combined for term in terms)

    @classmethod
    def matches_policy_metadata_tags(cls, statement: RegularPolicyStatement, field: str, terms_value: object) -> bool:
        terms = cls._as_terms(terms_value)
        if not terms:
            return True
        tag_text = cls._policy_tag_text(statement, field).casefold()
        return any(term.casefold() in tag_text for term in terms)

    @classmethod
    def query(
        cls,
        statements: list[RegularPolicyStatement],
        filters: PolicySearch | None = None,
    ) -> dict[str, Any]:
        """Return filtered tag-oriented statements with summary metadata."""

        filters = filters or {}
        enriched = cls.enrich_statements([stmt for stmt in statements if isinstance(stmt, dict)])
        matched = []
        for statement in enriched:
            if not cls.matches_tag_filters(statement, filters):
                continue
            if not cls.matches_condition_atom_terms(statement, filters.get('condition_atom_terms')):
                continue
            if not all(
                cls.matches_policy_metadata_tags(statement, field, filters.get(field))
                for field in POLICY_TAG_FILTER_FIELDS
            ):
                continue
            if filters and not cls._has_tag_query(filters) and not statement.get('tag_conditions'):
                continue
            matched.append(statement)

        semantics = Counter()
        namespaces = Counter()
        for statement in matched:
            for condition in statement.get('tag_conditions') or []:
                if not isinstance(condition, dict):
                    continue
                if condition.get('access_semantics'):
                    semantics[str(condition.get('access_semantics'))] += 1
                if condition.get('tag_namespace'):
                    namespaces[str(condition.get('tag_namespace'))] += 1

        return {
            'count': len(matched),
            'statements': matched,
            'summary': {
                'access_semantics': dict(semantics),
                'tag_namespaces': dict(namespaces),
            },
        }

    @classmethod
    def context_warnings_for_conditions(cls, tag_conditions: list[dict[str, Any]]) -> list[str]:
        warnings: list[str] = []
        semantics = {str(cond.get('access_semantics') or '') for cond in tag_conditions if isinstance(cond, dict)}
        if 'target_resource_tag' in semantics:
            warnings.extend(cls.TARGET_RESOURCE_WARNINGS)
        if 'target_compartment_tag' in semantics:
            warnings.extend(cls.TARGET_COMPARTMENT_WARNINGS)
        return warnings

    @classmethod
    def _condition_field_matches(cls, condition: dict[str, Any], field: str, terms: list[str]) -> bool:
        field_map = {
            'tag_access_type': 'access_type',
            'tag_access_semantics': 'access_semantics',
            'tag_namespace': 'tag_namespace',
            'tag_key': 'tag_key',
            'tag_value': 'value',
            'tag_operator': 'operator',
        }
        value = str(condition.get(field_map[field]) or '').casefold()
        return any(term.casefold() in value for term in terms)

    @staticmethod
    def _as_terms(value: object | None) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.split('|') if part.strip()]
        if isinstance(value, list | tuple | set):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value).strip()
        return [text] if text else []

    @staticmethod
    def _infer_value_type(value: object) -> str:
        text = str(value or '').strip()
        if not text:
            return ''
        if ',' in text:
            return 'list'
        if text.startswith('/') and text.endswith('/'):
            return 'pattern'
        if text == '*':
            return 'wildcard'
        return 'literal'

    @staticmethod
    def _infer_right_kind(value: object) -> str:
        text = str(value or '').strip()
        return 'variable' if '.tag.' in text or text.startswith('request.') or text.startswith('target.') else 'literal'

    @staticmethod
    def _policy_tag_text(statement: RegularPolicyStatement, field: str) -> str:
        buckets: list[object] = []
        if field in {'policy_tag', 'policy_freeform_tag'}:
            buckets.append(statement.get('policy_freeform_tags') or statement.get('freeform_tags'))
        if field in {'policy_tag', 'policy_defined_tag'}:
            buckets.append(statement.get('policy_defined_tags') or statement.get('defined_tags'))
        if field == 'policy_tag':
            buckets.append(statement.get('policy_tags') or statement.get('tags'))
        return ' '.join(cls_text for bucket in buckets if (cls_text := TagBasedPolicyService._flatten_tag_text(bucket)))

    @staticmethod
    def _flatten_tag_text(value: object) -> str:
        if isinstance(value, dict):
            parts: list[str] = []
            for key, item in value.items():
                parts.append(str(key))
                parts.append(TagBasedPolicyService._flatten_tag_text(item))
            return ' '.join(parts)
        if isinstance(value, list | tuple | set):
            return ' '.join(TagBasedPolicyService._flatten_tag_text(item) for item in value)
        return '' if value is None else str(value)

    @staticmethod
    def _has_tag_query(filters: PolicySearch) -> bool:
        return bool(set(filters) & (TAG_FILTER_FIELDS | POLICY_TAG_FILTER_FIELDS | {'condition_atom_terms'}))
