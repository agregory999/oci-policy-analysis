"""Service facade for policy-browser-style utility datasets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.common.logger import get_logger


@dataclass
class PolicyBrowserService:
    """Build utility-friendly datasets from loaded policy repository data."""

    context: AppContext

    def __post_init__(self) -> None:
        self.logger = get_logger(component='policy_browser_service')

    def list_compartment_hierarchy(self) -> dict[str, object]:
        """Return compartment hierarchy rows with statement limit status metadata."""
        repo = self.context.policy_repo
        compartments = list(getattr(repo, 'compartments', []) or [])
        policies = list(getattr(repo, 'policies', []) or [])

        policy_counts_by_compartment: dict[str, int] = {}
        for policy in policies:
            compartment_ocid = str(policy.get('compartment_ocid') or '')
            if not compartment_ocid:
                continue
            policy_counts_by_compartment[compartment_ocid] = policy_counts_by_compartment.get(compartment_ocid, 0) + 1

        rows: list[dict[str, object]] = []
        for comp in compartments:
            name = str(comp.get('name') or '(Unnamed Compartment)')
            ocid = str(comp.get('id') or '')
            path = str(comp.get('path') or comp.get('compartment_path') or name)
            hierarchy_path = str(comp.get('hierarchy_path') or path)
            description = str(comp.get('description') or '')
            parent_ocid = str(comp.get('parent_id') or '')
            direct_count = int(comp.get('statement_count_direct') or 0)
            cumulative_count = int(comp.get('statement_count_cumulative') or 0)
            if cumulative_count > 500:
                limit_state = 'over'
            elif cumulative_count >= 450:
                limit_state = 'warning'
            else:
                limit_state = 'ok'

            rows.append(
                {
                    'compartment_name': name,
                    'compartment_ocid': ocid,
                    'compartment_path': path,
                    'hierarchy_path': hierarchy_path,
                    'description': description,
                    'parent_ocid': parent_ocid,
                    'policy_count': policy_counts_by_compartment.get(ocid, 0),
                    'statement_count_direct': direct_count,
                    'statement_count_cumulative': cumulative_count,
                    'limit_state': limit_state,
                }
            )

        rows.sort(key=lambda row: str(row.get('compartment_path') or '').casefold())
        self.logger.info('Compartment hierarchy utility rows built: %d', len(rows))
        return {
            'total': len(rows),
            'rows': rows,
        }

    def list_tag_namespaces(self) -> dict[str, object]:
        """Return tag namespace/key/value catalog rows for utility rendering."""
        namespace_catalog = self._collect_defined_tag_namespace_keys()
        rows: list[dict[str, object]] = []
        for namespace in sorted(namespace_catalog.keys(), key=lambda value: value.casefold()):
            entry = namespace_catalog[namespace]
            compartment_path = str(entry.get('compartment_path') or 'UNKNOWN_PATH')
            keys = entry.get('keys') or {}
            if not isinstance(keys, dict):
                keys = {}
            key_names = sorted([str(k) for k in keys.keys()], key=lambda value: value.casefold())
            if not key_names:
                rows.append(
                    {
                        'namespace': namespace,
                        'compartment_path': compartment_path,
                        'key_name': '(no keys discovered)',
                        'values': [],
                    }
                )
                continue

            for key_name in key_names:
                value_choices = keys.get(key_name)
                values: list[str] = []
                if isinstance(value_choices, list | tuple | set):
                    values = sorted(
                        {str(v) for v in value_choices if v is not None}, key=lambda value: value.casefold()
                    )
                rows.append(
                    {
                        'namespace': namespace,
                        'compartment_path': compartment_path,
                        'key_name': key_name,
                        'values': values,
                    }
                )

        self.logger.info('Tag namespace utility rows built: %d', len(rows))
        return {
            'total': len(rows),
            'rows': rows,
        }

    def _collect_defined_tag_namespace_keys(self) -> dict[str, dict[str, Any]]:
        """Collect namespace catalog rows, including keys + compartment path."""
        repo = self.context.policy_repo
        repo_catalog = getattr(repo, 'defined_tag_namespace_keys', None)
        if isinstance(repo_catalog, dict) and repo_catalog:
            normalized: dict[str, dict[str, Any]] = {}
            for ns, entry in repo_catalog.items():
                ns_str = str(ns)
                if isinstance(entry, dict):
                    raw_keys = entry.get('keys') or {}
                    key_map: dict[str, list[str] | None] = {}
                    if isinstance(raw_keys, dict):
                        for key_name, value_choices in raw_keys.items():
                            key_str = str(key_name)
                            if isinstance(value_choices, list | tuple | set):
                                key_map[key_str] = sorted({str(v) for v in value_choices if v is not None}) or None
                            else:
                                key_map[key_str] = None
                    else:
                        for key_name in raw_keys:
                            key_map[str(key_name)] = None
                    comp_ocid = entry.get('compartment_ocid')
                    comp_path = entry.get('compartment_path')
                else:
                    key_map = {str(k): None for k in (entry or [])}
                    comp_ocid = None
                    comp_path = None

                if not comp_path and hasattr(repo, 'get_compartment_path_for_ocid'):
                    comp_path = repo.get_compartment_path_for_ocid(comp_ocid)

                normalized[ns_str] = {
                    'keys': key_map,
                    'compartment_ocid': comp_ocid,
                    'compartment_path': comp_path or 'UNKNOWN_PATH',
                }
            return normalized

        namespace_to_rows: dict[str, dict[str, Any]] = {}
        policies = repo.policies or []
        for policy in policies:
            defined_tags = policy.get('defined_tags') or {}
            if not isinstance(defined_tags, dict):
                continue
            for namespace, value in defined_tags.items():
                namespace_str = str(namespace)
                entry = namespace_to_rows.setdefault(
                    namespace_str,
                    {
                        'keys': {},
                        'compartment_ocid': policy.get('compartment_ocid'),
                        'compartment_path': policy.get('compartment_path')
                        or repo.get_compartment_path_for_ocid(policy.get('compartment_ocid')),
                    },
                )
                key_map = entry.setdefault('keys', {})
                if not isinstance(key_map, dict):
                    key_map = {}
                    entry['keys'] = key_map
                if isinstance(value, dict):
                    for key_name in value.keys():
                        key_map[str(key_name)] = None
                else:
                    key_map['(value)'] = None
        return namespace_to_rows
