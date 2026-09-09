"""Historical cache comparison service with stable-key normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from oci_policy_analysis.application.core.support.logger import get_logger


@dataclass
class HistoricalDiffItem:
    """Describe one added, removed, or modified item in a cache comparison."""

    action: str
    section: str
    stable_key: str
    title: str
    old_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None
    changed_fields: list[dict[str, Any]] | None = None


@dataclass
class HistoricalSectionResult:
    """Summarize changes for one historical comparison section."""

    section: str
    key: str
    added: int
    removed: int
    modified: int
    items: list[HistoricalDiffItem]


@dataclass
class HistoricalCompareResult:
    """Contain the normalized results of comparing two cache snapshots."""

    left_cache: str
    right_cache: str
    policy_sections: list[HistoricalSectionResult]
    identity_sections: list[HistoricalSectionResult]
    identity_comparable: bool = True


class HistoricalAnalysisService:
    """Compare two cache snapshots and return normalized sectioned results."""

    POLICY_SECTIONS: list[tuple[str, str]] = [
        ('Policies', 'policies'),
        ('Regular Statements', 'policy_statements'),
        ('Defined Aliases', 'defined_aliases'),
        ('Cross-Tenancy Statements', 'cross_tenancy_statements'),
    ]
    IDENTITY_SECTIONS: list[tuple[str, str]] = [
        ('Identity Domains', 'identity_domains'),
        ('Groups', 'groups'),
        ('Dynamic Groups', 'dynamic_groups'),
        ('Users', 'users'),
    ]

    def __init__(self, cache_manager) -> None:
        self.cache_manager = cache_manager
        self.logger = get_logger(component='historical_analysis_service')

    @staticmethod
    def _title_for(section_label: str, row: dict[str, Any]) -> str:
        if section_label == 'Policies':
            return str(row.get('policy_name') or row.get('policy_ocid') or row.get('stable_key') or '(policy)')
        if section_label == 'Regular Statements':
            return str(
                row.get('statement_text')
                or f"{row.get('compartment_path', '')}/{row.get('policy_name', '')}".strip('/')
                or row.get('stable_key')
                or '(statement)'
            )
        if section_label == 'Defined Aliases':
            return str(
                f"{row.get('policy_name', '')}/{row.get('defined_type', '')}/{row.get('defined_name', '')}".strip('/')
                or row.get('stable_key')
                or '(alias)'
            )
        if section_label == 'Cross-Tenancy Statements':
            return str(
                row.get('statement_text') or row.get('policy_name') or row.get('stable_key') or '(cross-tenancy)'
            )
        if section_label == 'Identity Domains':
            return str(
                row.get('display_name') or row.get('name') or row.get('id') or row.get('stable_key') or '(domain)'
            )
        if section_label == 'Groups':
            return str(
                f"{row.get('domain_name', '')}/{row.get('group_name', '')}".strip('/')
                or row.get('group_ocid')
                or row.get('stable_key')
                or '(group)'
            )
        if section_label == 'Dynamic Groups':
            return str(
                f"{row.get('domain_name', '')}/{row.get('dynamic_group_name', '')}".strip('/')
                or row.get('dynamic_group_ocid')
                or row.get('stable_key')
                or '(dynamic-group)'
            )
        if section_label == 'Users':
            return str(
                f"{row.get('domain_name', '')}/{row.get('user_name', '')}".strip('/')
                or row.get('user_ocid')
                or row.get('stable_key')
                or '(user)'
            )
        return str(row.get('stable_key') or '(item)')

    @staticmethod
    def _fallback_stable_key(section_key: str, row: dict[str, Any], idx: int) -> str:
        """Best-effort stable key for legacy caches that lack stable_key fields."""
        if section_key == 'policies':
            return str(row.get('policy_ocid') or row.get('policy_name') or f'policies#{idx}')
        if section_key == 'policy_statements':
            subject = row.get('subject')
            if isinstance(subject, list):
                subject_value = '|'.join(sorted(str(v) for v in subject))
            else:
                subject_value = str(subject or '')
            identity = (
                f"{row.get('policy_ocid') or row.get('policy_name') or ''}|"
                f"{row.get('compartment_ocid') or row.get('compartment_path') or ''}|"
                f"{row.get('subject_type') or ''}|{subject_value}|"
                f"{row.get('location_type') or ''}|{row.get('location') or ''}|"
                f"{row.get('conditions') or ''}|{row.get('comments') or ''}"
            )
            return str(identity or f'policy_statements#{idx}')
        if section_key == 'defined_aliases':
            return str(
                f"{row.get('policy_ocid') or row.get('policy_name') or ''}|"
                f"{row.get('defined_type') or ''}|{row.get('defined_name') or ''}|{row.get('ocid_alias') or ''}"
            )
        if section_key == 'cross_tenancy_statements':
            return str(
                row.get('internal_id')
                or row.get('policy_ocid')
                or row.get('statement_text')
                or f'cross_tenancy_statements#{idx}'
            )
        if section_key == 'identity_domains':
            return str(row.get('id') or row.get('display_name') or row.get('name') or f'identity_domains#{idx}')
        if section_key == 'groups':
            return str(
                row.get('group_ocid')
                or row.get('group_id')
                or f"{row.get('domain_name') or ''}/{row.get('group_name') or ''}"
                or f'groups#{idx}'
            )
        if section_key == 'dynamic_groups':
            return str(
                row.get('dynamic_group_ocid')
                or row.get('dynamic_group_id')
                or f"{row.get('domain_name') or ''}/{row.get('dynamic_group_name') or ''}"
                or f'dynamic_groups#{idx}'
            )
        if section_key == 'users':
            return str(
                row.get('user_ocid')
                or row.get('user_id')
                or f"{row.get('domain_name') or ''}/{row.get('user_name') or ''}"
                or f'users#{idx}'
            )
        return f'{section_key}#{idx}'

    @staticmethod
    def _to_keyed_map(snapshot: dict[str, Any], key: str) -> dict[str, dict[str, Any]]:
        by_key_name = f'{key}_by_key'
        existing = snapshot.get(by_key_name)
        if key == 'identity_domains' and not existing:
            existing = snapshot.get('domains_by_key')
        if isinstance(existing, dict) and existing:
            return {str(k): v for k, v in existing.items() if isinstance(v, dict)}

        rows = snapshot.get(key, [])
        if key == 'identity_domains' and not rows:
            rows = snapshot.get('domains', [])
        result: dict[str, dict[str, Any]] = {}
        if not isinstance(rows, list):
            return result
        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            stable = str(row.get('stable_key') or HistoricalAnalysisService._fallback_stable_key(key, row, idx))
            row_copy = dict(row)
            row_copy.setdefault('stable_key', stable)
            result[stable] = row_copy
        return result

    def _compare_section(
        self,
        left: dict[str, Any],
        right: dict[str, Any],
        *,
        label: str,
        key: str,
    ) -> HistoricalSectionResult:
        left_map = self._to_keyed_map(left, key)
        right_map = self._to_keyed_map(right, key)

        left_keys = set(left_map.keys())
        right_keys = set(right_map.keys())

        added_keys = sorted(right_keys - left_keys)
        removed_keys = sorted(left_keys - right_keys)
        shared_keys = sorted(left_keys & right_keys)

        items: list[HistoricalDiffItem] = []
        for stable_key in added_keys:
            new_val = right_map[stable_key]
            items.append(
                HistoricalDiffItem(
                    action='Added',
                    section=label,
                    stable_key=stable_key,
                    title=self._title_for(label, new_val),
                    new_value=new_val,
                )
            )
        for stable_key in removed_keys:
            old_val = left_map[stable_key]
            items.append(
                HistoricalDiffItem(
                    action='Removed',
                    section=label,
                    stable_key=stable_key,
                    title=self._title_for(label, old_val),
                    old_value=old_val,
                )
            )

        modified_count = 0
        for stable_key in shared_keys:
            old_val = left_map[stable_key]
            new_val = right_map[stable_key]
            if old_val != new_val:
                modified_count += 1
                changed_fields = self._extract_changed_fields(old_val, new_val)
                items.append(
                    HistoricalDiffItem(
                        action='Modified',
                        section=label,
                        stable_key=stable_key,
                        title=self._title_for(label, new_val),
                        old_value=old_val,
                        new_value=new_val,
                        changed_fields=changed_fields,
                    )
                )

        return HistoricalSectionResult(
            section=label,
            key=key,
            added=len(added_keys),
            removed=len(removed_keys),
            modified=modified_count,
            items=items,
        )

    @staticmethod
    def _extract_changed_fields(old_val: dict[str, Any], new_val: dict[str, Any]) -> list[dict[str, Any]]:
        """Return recursive field-level deltas using dotted/indexed paths.

        Example paths:
        - policy_name
        - principals[0].display_name
        - tags.defined.cost_center
        """

        changed: list[dict[str, Any]] = []

        def _walk(old_item: Any, new_item: Any, path: str) -> None:
            if isinstance(old_item, dict) and isinstance(new_item, dict):
                keys = sorted(set(old_item.keys()) | set(new_item.keys()))
                for key in keys:
                    if isinstance(key, str) and key.startswith('_'):
                        continue
                    child_path = f'{path}.{key}' if path else str(key)
                    _walk(old_item.get(key), new_item.get(key), child_path)
                return

            if isinstance(old_item, list) and isinstance(new_item, list):
                max_len = max(len(old_item), len(new_item))
                for idx in range(max_len):
                    old_child = old_item[idx] if idx < len(old_item) else None
                    new_child = new_item[idx] if idx < len(new_item) else None
                    child_path = f'{path}[{idx}]' if path else f'[{idx}]'
                    _walk(old_child, new_child, child_path)
                return

            if old_item != new_item:
                changed.append({'field': path or '(value)', 'old': old_item, 'new': new_item})

        _walk(old_val, new_val, '')
        return changed

    def compare_caches(self, *, left_cache: str, right_cache: str) -> HistoricalCompareResult:
        left = self.cache_manager.load_cache_into_local_json(cached_tenancy=left_cache) or {}
        right = self.cache_manager.load_cache_into_local_json(cached_tenancy=right_cache) or {}
        if not isinstance(left, dict) or not isinstance(right, dict):
            raise ValueError('Unable to load cache json for historical comparison.')

        policy_sections = [
            self._compare_section(left, right, label=label, key=key) for label, key in self.POLICY_SECTIONS
        ]
        policy_only = any(
            snapshot.get('snapshot_kind') == 'policy_reload' or bool(snapshot.get('policy_data_reloaded'))
            for snapshot in (left, right)
        )
        identity_sections = (
            []
            if policy_only
            else [self._compare_section(left, right, label=label, key=key) for label, key in self.IDENTITY_SECTIONS]
        )

        self.logger.info(
            'Historical compare complete: left=%s right=%s policy_sections=%s identity_sections=%s',
            left_cache,
            right_cache,
            len(policy_sections),
            len(identity_sections),
        )
        return HistoricalCompareResult(
            left_cache=left_cache,
            right_cache=right_cache,
            policy_sections=policy_sections,
            identity_sections=identity_sections,
            identity_comparable=not policy_only,
        )
