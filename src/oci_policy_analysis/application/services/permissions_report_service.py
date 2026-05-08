"""Service facade for permissions report tree/detail workflows.

This module centralizes permissions-report shaping logic so web and Tk UI layers
can share the same inheritance and filtering behavior.
"""

from __future__ import annotations

from typing import Any

from oci_policy_analysis.application.context import AppContext


class PermissionsReportService:
    """Provide UI-agnostic permissions report operations.

    Args:
        context: Shared application context containing the policy intelligence engine.
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
    ) -> dict[str, Any]:
        """Return a tree payload grouped by effective path and subject.

        Args:
            show_inherited_principals: When True, include subjects inherited from
                ancestor compartment paths.
            principal_query: Optional free-text filter matched against principal keys.

        Returns:
            dict[str, Any]: Tree payload with sorted paths and subject rows.
        """
        report_data = self._report_data()
        query_terms = self._query_terms(principal_query)
        paths: list[dict[str, Any]] = []
        for path in sorted(report_data.keys()):
            subject_rows = self._subjects_for_path(
                path=path,
                report_data=report_data,
                show_inherited_principals=show_inherited_principals,
                principal_query_terms=query_terms,
            )
            paths.append({'path': path, 'subjects': subject_rows})
        return {'paths': paths}

    def get_details(
        self,
        *,
        path_key: str,
        subject_key: str,
        permission_query: str = '',
    ) -> dict[str, Any]:
        """Return allow/deny detail rows for a selected path/subject pair.

        Args:
            path_key: Effective compartment path selected by the user.
            subject_key: Canonical principal key selected by the user.
            permission_query: Optional free-text filter matched against permission text.

        Returns:
            dict[str, Any]: Details payload containing allow and deny row lists.
        """
        engine_payload = self._engine_payload()
        report_data = self._report_data()
        perm_conditionals = engine_payload.get('perm_conditionals', {}) if engine_payload else {}
        perm_statements = engine_payload.get('perm_statements', {}) if engine_payload else {}

        subject_data = report_data.get(path_key, {}).get(subject_key, {})
        allow = list(subject_data.get('allow', []))
        deny = list(subject_data.get('deny', []))

        parent_nodes = self._ancestor_paths(path_key)
        parent_allows: list[tuple[str, list[str]]] = []
        parent_denies: list[tuple[str, list[str]]] = []
        for ancestor in parent_nodes:
            ancestor_data = report_data.get(ancestor, {}).get(subject_key, {})
            ap_all = ancestor_data.get('allow', [])
            ap_deny = ancestor_data.get('deny', [])
            if ap_all:
                parent_allows.append((ancestor, ap_all))
            if ap_deny:
                parent_denies.append((ancestor, ap_deny))

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

    def get_export_payload(self) -> dict[str, Any]:
        """Return raw report data used for JSON export.

        Returns:
            dict[str, Any]: Current permissions report mapping grouped by path and subject.
        """
        return {'report': self._report_data()}

    def _engine_payload(self) -> dict[str, Any]:
        payload = getattr(self.context.intelligence, 'permissions_report', {}) or {}
        return payload if isinstance(payload, dict) else {}

    def _report_data(self) -> dict[str, Any]:
        payload = self._engine_payload()
        report = payload.get('report', {}) if payload else {}
        return report if isinstance(report, dict) else {}

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
    ) -> list[dict[str, Any]]:
        subjects = report_data.get(path, {})
        subject_map: dict[str, tuple[str, str | None]] = {}
        for subject_key, data in subjects.items():
            subject_type = (data or {}).get('subject_type') or 'unknown'
            subject_map[subject_key] = (subject_type, None)
        if show_inherited_principals:
            for ancestor in self._ancestor_paths(path):
                for subject_key, data in report_data.get(ancestor, {}).items():
                    if subject_key in subject_map:
                        continue
                    subject_type = (data or {}).get('subject_type') or 'unknown'
                    subject_map[subject_key] = (subject_type, ancestor)

        rows: list[dict[str, Any]] = []
        for subject_key, (subject_type, inherited_from) in sorted(subject_map.items(), key=lambda item: item[0]):
            if principal_query_terms and not self._matches_all_terms(subject_key, principal_query_terms):
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
