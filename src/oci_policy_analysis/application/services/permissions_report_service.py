"""Service facade for permissions report tree/detail workflows.

This module centralizes permissions-report shaping logic so web and Tk UI layers
can share the same inheritance and filtering behavior.
"""

from __future__ import annotations

from typing import Any

from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.application.core.policy_corpus import permissions_report_projection


class PermissionsReportService:
    """Query projected permission contributions without UI dependencies.

    Args:
        context: Runtime with a full-profile permissions report; prospective views
            also require the active simulation engine.

    Attributes:
        context: Shared runtime read on each report operation.

    Notes:
        Reports retain allow/deny and conditional contributions. They do not evaluate
        final OCI access. A minimal load alone does not populate the full report.
    """

    def __init__(self, context: AppContext) -> None:
        """Initialize the permissions report service.

        Args:
            context: Shared application context.

        Returns:
            None
        """
        self.context = context

    def get_tree(
        self,
        *,
        show_inherited_principals: bool = False,
        principal_query: str = '',
        path_query: str = '',
        principal_type: str = '',
        include_prospective: bool = False,
    ) -> dict[str, Any]:
        """Return a tree grouped by effective path and principal.

        Args:
            show_inherited_principals: Include principals inherited from ancestor paths.
            principal_query: Whitespace-separated terms required in the principal key.
            path_query: Whitespace-separated terms required in the effective path.
            principal_type: Optional exact principal-type filter.
            include_prospective: Include the simulation engine's hypothetical overlay.

        Returns:
            dict[str, Any]: Sorted paths with principal rows and available principal types.
        """
        report_data = self._report_data(include_prospective=include_prospective)
        query_terms = self._query_terms(principal_query)
        path_terms = self._query_terms(path_query)
        principal_types = sorted(
            {
                str((subject_data or {}).get('subject_type') or 'unknown')
                for subjects in report_data.values()
                for subject_data in subjects.values()
            },
            key=str.casefold,
        )
        paths: list[dict[str, Any]] = []
        for path in sorted(report_data.keys()):
            if path_terms and not self._matches_all_terms(path, path_terms):
                continue
            subject_rows = self._subjects_for_path(
                path=path,
                report_data=report_data,
                show_inherited_principals=show_inherited_principals,
                principal_query_terms=query_terms,
                principal_type=principal_type,
            )
            paths.append({'path': path, 'subjects': subject_rows})
        return {'paths': paths, 'principal_types': principal_types}

    def get_details(
        self,
        *,
        path_key: str,
        subject_key: str,
        permission_query: str = '',
        include_prospective: bool = False,
        include_inherited: bool = False,
    ) -> dict[str, Any]:
        """Return allow/deny contribution rows for a path/principal pair.

        Args:
            path_key: Effective compartment path selected from the report tree.
            subject_key: Canonical principal key selected from the report tree.
            permission_query: Optional terms required in the permission text.
            include_prospective: Include the hypothetical simulation overlay.
            include_inherited: Include contributions from ancestor grant paths.

        Returns:
            dict[str, Any]: Path, subject identity, and allow_rows/deny_rows with source
            evidence and condition details where available.
        """
        engine_payload = self._engine_payload(include_prospective=include_prospective)
        report_data = self._report_data(include_prospective=include_prospective)
        perm_conditionals = engine_payload.get('perm_conditionals', {}) if engine_payload else {}
        perm_statements = engine_payload.get('perm_statements', {}) if engine_payload else {}

        subject_data = report_data.get(path_key, {}).get(subject_key, {})
        allow = list(subject_data.get('allow', []))
        deny = list(subject_data.get('deny', []))

        parent_nodes = self._ancestor_paths(path_key)
        parent_allows: list[tuple[str, list[str]]] = []
        parent_denies: list[tuple[str, list[str]]] = []
        for ancestor in parent_nodes if include_inherited else []:
            ancestor_data = report_data.get(ancestor, {}).get(subject_key, {})
            ap_all = ancestor_data.get('allow', [])
            ap_deny = ancestor_data.get('deny', [])
            if ap_all:
                parent_allows.append((ancestor, ap_all))
            if ap_deny:
                parent_denies.append((ancestor, ap_deny))

        corpus_rows = engine_payload.get('grant_rows') or []
        if corpus_rows:
            allow_rows = self._corpus_detail_rows(
                corpus_rows, path_key, subject_key, 'allow', include_inherited=include_inherited
            )
            deny_rows = self._corpus_detail_rows(
                corpus_rows, path_key, subject_key, 'deny', include_inherited=include_inherited
            )
        else:
            allow_rows = self._build_permission_rows(
                permissions=allow,
                parent_permissions=parent_allows,
                perm_conditionals=perm_conditionals,
                perm_statements=perm_statements,
                path_key=path_key,
                subject_key=subject_key,
            )
            deny_rows = self._build_permission_rows(
                permissions=deny,
                parent_permissions=parent_denies,
                perm_conditionals=perm_conditionals,
                perm_statements=perm_statements,
                path_key=path_key,
                subject_key=subject_key,
            )

        permission_terms = self._query_terms(permission_query)
        allow_rows = self._filter_permission_rows(allow_rows, permission_terms)
        deny_rows = self._filter_permission_rows(deny_rows, permission_terms)

        return {
            'path': path_key,
            'subject_key': subject_key,
            'allow_rows': allow_rows,
            'deny_rows': deny_rows,
        }

    def get_export_payload(self, *, include_prospective: bool = False) -> dict[str, Any]:
        """Return an export container for the selected report.

        Args:
            include_prospective: Include the hypothetical simulation overlay.

        Returns:
            dict[str, Any]: Report tree, grant rows, exclusions, and summary counts.
        """
        payload = self._engine_payload(include_prospective=include_prospective)
        return {
            'report': self._report_data(include_prospective=include_prospective),
            'grant_rows': list(payload.get('grant_rows') or []),
            'exclusions': list(payload.get('exclusions') or []),
            'summary': dict(payload.get('summary') or {}),
        }

    def get_export_rows(self) -> list[dict[str, Any]]:
        """Return flat report rows for CSV and tabular export workflows."""
        payload = self._engine_payload()
        rows = payload.get('grant_rows') or []
        return [dict(row) for row in rows if isinstance(row, dict)]

    def get_exclusions(self, *, include_prospective: bool = False) -> list[dict[str, Any]]:
        """Return source statements omitted from regular corpus permission facts.

        Args:
            include_prospective: Include exclusions from hypothetical statements.

        Returns:
            list[dict[str, Any]]: Exclusion records with source evidence and reasons.
        """
        rows = self._engine_payload(include_prospective=include_prospective).get('exclusions') or []
        return [dict(row) for row in rows if isinstance(row, dict)]

    def _engine_payload(self, *, include_prospective: bool = False) -> dict[str, Any]:
        if include_prospective:
            simulation = getattr(self.context, 'simulation', None)
            get_corpus = getattr(simulation, 'get_corpus', None)
            if callable(get_corpus):
                corpus = get_corpus(include_prospective=True)
                if corpus is not None:
                    return permissions_report_projection(corpus)
        payload = getattr(self.context.intelligence, 'permissions_report', {}) or {}
        return payload if isinstance(payload, dict) else {}

    def _report_data(self, *, include_prospective: bool = False) -> dict[str, Any]:
        payload = self._engine_payload(include_prospective=include_prospective)
        report = payload.get('report', {}) if payload else {}
        if not isinstance(report, dict):
            return {}
        # Different source statements can spell the same effective path or
        # principal key with different casing. Fold those variants together
        # for an unambiguous composite path/principal row in the tree.
        grouped: dict[str, dict[str, Any]] = {}
        for path in sorted(report, key=lambda value: (str(value).casefold(), str(value))):
            path_key = self._canonical_path(path)
            path_row = grouped.setdefault(path_key, {'display_path': str(path), 'subjects': {}})
            subjects = report.get(path, {})
            if not isinstance(subjects, dict):
                continue
            for subject_key in sorted(subjects, key=lambda value: (str(value).casefold(), str(value))):
                subject_data = subjects.get(subject_key) or {}
                subject_token = str(subject_key).casefold()
                merged = path_row['subjects'].setdefault(
                    subject_token,
                    {
                        'display_key': str(subject_key),
                        'subject_type': (subject_data or {}).get('subject_type') or str(subject_key).split(':', 1)[0],
                        'allow': set(),
                        'deny': set(),
                    },
                )
                for effect in ('allow', 'deny'):
                    merged[effect].update(str(value) for value in (subject_data or {}).get(effect, []) or [])

        normalized: dict[str, Any] = {}
        for path_row in grouped.values():
            normalized_subjects = {}
            for subject in path_row['subjects'].values():
                normalized_subjects[subject['display_key']] = {
                    'subject_type': subject['subject_type'],
                    'allow': sorted(subject['allow']),
                    'deny': sorted(subject['deny']),
                }
            normalized[path_row['display_path']] = normalized_subjects
        return normalized

    @staticmethod
    def _corpus_detail_rows(
        rows: list[dict[str, Any]],
        path_key: str,
        subject_key: str,
        effect: str,
        *,
        include_inherited: bool,
    ) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str, bool], dict[str, Any]] = {}
        for raw in rows:
            if (
                PermissionsReportService._canonical_path(raw.get('effective_path'))
                != PermissionsReportService._canonical_path(path_key)
                or str(raw.get('principal_key') or '').casefold() != subject_key.casefold()
                or str(raw.get('action') or '') != effect
            ):
                continue
            if raw.get('inherited_from') and not include_inherited:
                continue
            key = (
                str(raw.get('permission') or ''),
                str(raw.get('inherited_from') or ''),
                bool(raw.get('prospective')),
            )
            row = grouped.setdefault(
                key,
                {
                    'permission': key[0],
                    'permission_key': key[0],
                    'conditional': False,
                    'statement_text': [],
                    'inherited_from': key[1] or None,
                    'prospective': key[2],
                    'inherited': bool(key[1]),
                },
            )
            row['conditional'] = row['conditional'] or bool(raw.get('conditional'))
            statement_text = str(raw.get('statement_text') or '')
            if statement_text and statement_text not in row['statement_text']:
                row['statement_text'].append(statement_text)
        result = []
        for row in grouped.values():
            row['statement_text'] = '\n\n'.join(row['statement_text'])
            result.append(row)
        return sorted(
            result, key=lambda row: (row['permission'], bool(row['prospective']), row['inherited_from'] or '')
        )

    @staticmethod
    def _query_terms(query: str) -> list[str]:
        return [term.casefold() for term in str(query or '').split() if term.strip()]

    @staticmethod
    def _matches_all_terms(value: str, terms: list[str]) -> bool:
        haystack = str(value or '').casefold()
        return all(term in haystack for term in terms)

    def _subjects_for_path(
        self,
        *,
        path: str,
        report_data: dict[str, Any],
        show_inherited_principals: bool,
        principal_query_terms: list[str],
        principal_type: str,
    ) -> list[dict[str, Any]]:
        subjects = report_data.get(path, {})
        subject_map: dict[str, tuple[str, str, str | None]] = {}
        for subject_key, data in subjects.items():
            subject_type = (data or {}).get('subject_type') or 'unknown'
            subject_map[subject_key.casefold()] = (subject_key, subject_type, None)
        if show_inherited_principals:
            for ancestor in self._ancestor_paths(path):
                ancestor_key = self._find_path_key(report_data, ancestor)
                for subject_key, data in report_data.get(ancestor_key, {}).items():
                    subject_token = subject_key.casefold()
                    if subject_token in subject_map:
                        continue
                    subject_type = (data or {}).get('subject_type') or 'unknown'
                    subject_map[subject_token] = (subject_key, subject_type, ancestor_key)

        rows: list[dict[str, Any]] = []
        for subject_key, subject_type, inherited_from in sorted(
            subject_map.values(), key=lambda item: item[0].casefold()
        ):
            if principal_query_terms and not self._matches_all_terms(subject_key, principal_query_terms):
                continue
            if (
                principal_type
                and principal_type.casefold() != 'all types'
                and subject_type.casefold() != principal_type.casefold()
            ):
                continue
            display_name = f'{subject_key} (inherited from {inherited_from})' if inherited_from else subject_key
            rows.append(
                {
                    'subject_key': subject_key,
                    'subject_type': subject_type,
                    'inherited_from': inherited_from,
                    'display_name': display_name,
                }
            )
        return rows

    @staticmethod
    def _ancestor_paths(path_key: str) -> list[str]:
        parent_path = path_key
        parent_nodes: list[str] = []
        while parent_path:
            if '/' in parent_path:
                parent_path = parent_path.rsplit('/', 1)[0]
            elif parent_path != 'ROOT':
                parent_path = 'ROOT'
            else:
                break
            parent_nodes.append(parent_path)
        return parent_nodes

    @staticmethod
    def _canonical_path(path: object) -> str:
        return str(path or '').strip().strip('/').casefold()

    @staticmethod
    def _find_path_key(report_data: dict[str, Any], path: str) -> str:
        wanted = PermissionsReportService._canonical_path(path)
        return next((key for key in report_data if PermissionsReportService._canonical_path(key) == wanted), path)

    @staticmethod
    def _build_permission_rows(
        *,
        permissions: list[str],
        parent_permissions: list[tuple[str, list[str]]],
        perm_conditionals: dict[tuple[str, str, str], bool],
        perm_statements: dict[tuple[str, str, str], str],
        path_key: str,
        subject_key: str,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for perm in sorted(permissions):
            rows.append(
                {
                    'permission': perm,
                    'permission_key': perm,
                    'conditional': bool(perm_conditionals.get((path_key, subject_key, perm), False)),
                    'statement_text': perm_statements.get((path_key, subject_key, perm), ''),
                    'inherited_from': None,
                    'inherited': False,
                }
            )
        for ancestor, ancestor_perms in parent_permissions:
            for perm in sorted(ancestor_perms):
                rows.append(
                    {
                        'permission': f'{perm} (inherited from {ancestor})',
                        'permission_key': perm,
                        'conditional': bool(perm_conditionals.get((ancestor, subject_key, perm), False)),
                        'statement_text': perm_statements.get((ancestor, subject_key, perm), ''),
                        'inherited_from': ancestor,
                        'inherited': True,
                    }
                )
        return rows

    def _filter_permission_rows(self, rows: list[dict[str, Any]], permission_terms: list[str]) -> list[dict[str, Any]]:
        if not permission_terms:
            return rows
        filtered: list[dict[str, Any]] = []
        for row in rows:
            permission_text = str(row.get('permission_key') or row.get('permission') or '')
            if self._matches_all_terms(permission_text, permission_terms):
                filtered.append(row)
        return filtered
