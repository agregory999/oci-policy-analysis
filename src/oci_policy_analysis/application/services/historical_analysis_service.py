"""Historical cache comparison service with stable-key normalization."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
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
    skipped_sections: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    section_warnings: dict[str, str] = field(default_factory=dict)


class HistoricalAnalysisService:
    """Compare two cache snapshots and return normalized sectioned results."""

    POLICY_SECTIONS: list[tuple[str, str]] = [
        ('Policies', 'policies'),
        ('Regular Statements', 'policy_statements'),
        ('Defined Aliases', 'defined_aliases'),
        ('Cross-Tenancy Statements', 'cross_tenancy_statements'),
    ]
    IDENTITY_SECTIONS: list[tuple[str, str]] = [
        ('Compartments', 'compartments'),
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
        if section_label == 'Compartments':
            return str(row.get('name') or row.get('compartment_name') or row.get('id') or '(compartment)')
        if section_label == 'Policies':
            return str(row.get('policy_name') or row.get('policy_ocid') or row.get('stable_key') or '(policy)')
        if section_label == 'Regular Statements':
            return str(
                row.get('statement_text')
                or f'{row.get("compartment_path", "")}/{row.get("policy_name", "")}'.strip('/')
                or row.get('stable_key')
                or '(statement)'
            )
        if section_label == 'Defined Aliases':
            return str(
                f'{row.get("policy_name", "")}/{row.get("defined_type", "")}/{row.get("defined_name", "")}'.strip('/')
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
                f'{row.get("domain_name", "")}/{row.get("group_name", "")}'.strip('/')
                or row.get('group_ocid')
                or row.get('stable_key')
                or '(group)'
            )
        if section_label == 'Dynamic Groups':
            return str(
                f'{row.get("domain_name", "")}/{row.get("dynamic_group_name", "")}'.strip('/')
                or row.get('dynamic_group_ocid')
                or row.get('stable_key')
                or '(dynamic-group)'
            )
        if section_label == 'Users':
            return str(
                f'{row.get("domain_name", "")}/{row.get("user_name", "")}'.strip('/')
                or row.get('user_ocid')
                or row.get('stable_key')
                or '(user)'
            )
        return str(row.get('stable_key') or '(item)')

    @staticmethod
    def _fallback_stable_key(section_key: str, row: dict[str, Any], idx: int) -> str:
        """Best-effort stable key for legacy caches that lack stable_key fields."""
        if section_key == 'compartments':
            return str(
                row.get('id')
                or row.get('compartment_ocid')
                or row.get('ocid')
                or row.get('name')
                or f'compartments#{idx}'
            )
        if section_key == 'policies':
            return str(row.get('policy_ocid') or row.get('policy_name') or f'policies#{idx}')
        if section_key == 'policy_statements':
            subject = row.get('subject')
            if isinstance(subject, list):
                subject_value = '|'.join(sorted(str(v) for v in subject))
            else:
                subject_value = str(subject or '')
            identity = (
                f'{row.get("policy_ocid") or row.get("policy_name") or ""}|'
                f'{row.get("compartment_ocid") or row.get("compartment_path") or ""}|'
                f'{row.get("subject_type") or ""}|{subject_value}|'
                f'{row.get("location_type") or ""}|{row.get("location") or ""}|'
                f'{row.get("conditions") or ""}|{row.get("comments") or ""}'
            )
            return str(identity or f'policy_statements#{idx}')
        if section_key == 'defined_aliases':
            return str(
                f'{row.get("policy_ocid") or row.get("policy_name") or ""}|'
                f'{row.get("defined_type") or ""}|{row.get("defined_name") or ""}|{row.get("ocid_alias") or ""}'
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
                or f'{row.get("domain_name") or ""}/{row.get("group_name") or ""}'
                or f'groups#{idx}'
            )
        if section_key == 'dynamic_groups':
            return str(
                row.get('dynamic_group_ocid')
                or row.get('dynamic_group_id')
                or f'{row.get("domain_name") or ""}/{row.get("dynamic_group_name") or ""}'
                or f'dynamic_groups#{idx}'
            )
        if section_key == 'users':
            return str(
                row.get('user_ocid')
                or row.get('user_id')
                or f'{row.get("domain_name") or ""}/{row.get("user_name") or ""}'
                or f'users#{idx}'
            )
        return f'{section_key}#{idx}'

    @staticmethod
    def _to_keyed_map(
        snapshot: dict[str, Any], key: str, *, meaningful_only: bool = False
    ) -> dict[str, dict[str, Any]]:
        by_key_name = f'{key}_by_key'
        existing = snapshot.get(by_key_name)
        if key == 'identity_domains' and not existing:
            existing = snapshot.get('domains_by_key')
        if meaningful_only and key in {'policy_statements', 'cross_tenancy_statements'}:
            # Statement text has no durable OCI row ID. Match exact source within
            # its policy; preserve duplicate occurrences instead of collapsing them.
            rows = snapshot.get(key)
            if not isinstance(rows, list):
                rows = list(existing.values()) if isinstance(existing, dict) else []
            result, occurrences = {}, {}
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                identity = [
                    row.get('policy_ocid') or row.get('policy_name'),
                    row.get('compartment_ocid') or row.get('compartment_path'),
                    row.get('statement_text'),
                ]
                if row.get('statement_text'):
                    base = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
                else:
                    base = str(row.get('stable_key') or HistoricalAnalysisService._fallback_stable_key(key, row, index))
                occurrence = occurrences.get(base, 0)
                occurrences[base] = occurrence + 1
                result[f'{base}#{occurrence}'] = dict(row)
            return result
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
        meaningful_only: bool = False,
    ) -> HistoricalSectionResult:
        left_map = self._to_keyed_map(left, key, meaningful_only=meaningful_only)
        right_map = self._to_keyed_map(right, key, meaningful_only=meaningful_only)

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
            comparison_old = self.comparison_value(old_val, meaningful_only=meaningful_only)
            comparison_new = self.comparison_value(new_val, meaningful_only=meaningful_only)
            changed_fields = self._extract_changed_fields(comparison_old, comparison_new)
            if changed_fields:
                modified_count += 1
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
    def comparison_value(value: Any, *, meaningful_only: bool = False) -> Any:
        """Return detached comparable JSON without ephemeral implementation fields.

        Args:
            value: JSON source value; never changed in place.
            meaningful_only: Also omit entity-level internal_id and stable_key fields.
                OCI IDs, timestamps, conditions, validity and array order remain.

        Returns:
            Any: Detached comparison value. Underscore-prefixed runtime fields
            are omitted only at the entity level. Nested JSON, including arbitrary
            OCI tag keys, is preserved literally.
        """
        if isinstance(value, dict):
            return deepcopy(
                {
                    key: child
                    for key, child in value.items()
                    if not str(key).startswith('_') and not (meaningful_only and key in {'internal_id', 'stable_key'})
                }
            )
        return deepcopy(value)

    @staticmethod
    def _extract_changed_fields(old_val: dict[str, Any], new_val: dict[str, Any]) -> list[dict[str, Any]]:
        """Return typed, presence-aware field deltas with unambiguous path tokens."""
        changed = []

        def walk(old, new, path, tokens, old_present=True, new_present=True):
            if old_present and new_present and isinstance(old, dict) and isinstance(new, dict):
                for key in sorted(set(old) | set(new)):
                    walk(
                        old.get(key),
                        new.get(key),
                        f'{path}.{key}' if path else str(key),
                        [*tokens, key],
                        key in old,
                        key in new,
                    )
                return
            if old_present and new_present and isinstance(old, list) and isinstance(new, list):
                for index in range(max(len(old), len(new))):
                    walk(
                        old[index] if index < len(old) else None,
                        new[index] if index < len(new) else None,
                        f'{path}[{index}]',
                        [*tokens, index],
                        index < len(old),
                        index < len(new),
                    )
                return
            if old_present != new_present or type(old) is not type(new) or old != new:
                changed.append(
                    {
                        'field': path or '(value)',
                        'path': tokens,
                        'old': deepcopy(old),
                        'new': deepcopy(new),
                        'old_present': old_present,
                        'new_present': new_present,
                        'action': 'Added' if not old_present else 'Removed' if not new_present else 'Modified',
                    }
                )

        walk(old_val, new_val, '', [])
        return changed

    @staticmethod
    def snapshot_kind(snapshot: dict[str, Any]) -> str:
        return snapshot.get('snapshot_kind') or ('policy_reload' if snapshot.get('policy_data_reloaded') else 'full')

    @classmethod
    def describe_snapshot(cls, snapshot: dict[str, Any]) -> str:
        kind = cls.snapshot_kind(snapshot)
        label = {
            'policy_reload': 'Policy / compartment reload (IAM inherited)',
            'full_reload': 'Reload All (IAM + policies)',
            'full': 'Full snapshot',
        }.get(kind, kind)
        lines = [f'Type: {label}']
        for key, title in [
            ('data_as_of', 'Data as of'),
            ('captured_at', 'Captured'),
            ('policy_data_reloaded', 'Policies reloaded'),
            ('identity_data_as_of', 'IAM as of'),
            ('reload_source_cache_name', 'Reload source'),
            ('base_cache_name', 'Base cache'),
        ]:
            if snapshot.get(key):
                lines.append(f'{title}: {snapshot[key]}')
        if snapshot.get('load_all_users') is False:
            lines.append('Users: not loaded')
        return '\n'.join(lines)

    @classmethod
    def _unavailable_reason(cls, snapshot: dict[str, Any], key: str, *, include_incomplete: bool = False) -> str:
        iam = key in {'identity_domains', 'groups', 'dynamic_groups', 'users'}
        if iam and cls.snapshot_kind(snapshot) == 'policy_reload':
            return 'IAM was inherited from the base cache, not refreshed by this policy reload.'
        if key == 'users' and snapshot.get('load_all_users') is False:
            return 'User inventory was not loaded.'
        if snapshot.get('inventory_complete') is False and not include_incomplete:
            return 'The load reported API errors; inventory may be incomplete.'
        capability = {
            'identity_domains': 'domains_inventory',
            'groups': 'groups_inventory',
            'dynamic_groups': 'dynamic_groups_inventory',
            'users': 'users_inventory',
        }.get(key)
        if capability and (snapshot.get('compliance_capabilities') or {}).get(capability) is False:
            return 'Inventory was not supplied by the compliance export.'
        aliases = [key, f'{key}_by_key']
        if key == 'identity_domains':
            aliases += ['domains', 'domains_by_key']
        if not any(isinstance(snapshot.get(alias), list | dict) for alias in aliases):
            return 'Inventory is missing from this cache.'
        return ''

    def compare_caches(
        self, *, left_cache: str, right_cache: str, meaningful_only: bool = False, include_incomplete: bool = False
    ) -> HistoricalCompareResult:
        """Read two caches and compare their sections without changing active data.

        Args:
            left_cache: Baseline cache name.
            right_cache: Target cache name.
            meaningful_only: Ignore ephemeral internal_id and stable_key fields.
            include_incomplete: Compare observed data despite incomplete-collection
                metadata, with warnings; differences do not establish OCI changes.

        Returns:
            HistoricalCompareResult: Sectioned changes and coverage limitations.
        """
        left = self.cache_manager.load_cache_into_local_json(cached_tenancy=left_cache)
        right = self.cache_manager.load_cache_into_local_json(cached_tenancy=right_cache)
        return self.compare_snapshots(
            left,
            right,
            left_name=left_cache,
            right_name=right_cache,
            meaningful_only=meaningful_only,
            include_incomplete=include_incomplete,
        )

    def compare_snapshots(
        self,
        left: dict,
        right: dict,
        *,
        left_name: str = 'Baseline',
        right_name: str = 'Target',
        meaningful_only: bool = False,
        include_incomplete: bool = False,
    ) -> HistoricalCompareResult:
        """Compare detached JSON snapshots using the same cache compatibility rules.

        Args:
            left: Baseline combined-cache JSON.
            right: Target combined-cache JSON.
            left_name: Display name for the baseline.
            right_name: Display name for the target.
            meaningful_only: Omit ephemeral internal IDs; preserve original evidence.
            include_incomplete: Compare available sections even when collection was
                incomplete. Missing target records are unverified snapshot differences.

        Returns:
            HistoricalCompareResult: Changes plus per-section non-comparison reasons.

        Raises:
            ValueError: Either snapshot is missing or known tenancy OCIDs differ.

        Notes:
            List items align by stable keys, with legacy fallback identities. An
            identity change can appear as removal/addition rather than modification.
            Meaningful mode aligns statements by exact text within a policy and retains
            duplicate occurrences; edits appear as removal/addition. Nested JSON
            arrays retain their order. No source files or engines change.
        """
        if not isinstance(left, dict) or not left or not isinstance(right, dict) or not right:
            raise ValueError('Unable to load cache json for historical comparison.')
        if left.get('tenancy_ocid') and right.get('tenancy_ocid') and left['tenancy_ocid'] != right['tenancy_ocid']:
            raise ValueError('Select two snapshots from the same tenancy.')

        skipped, warnings = {}, {}
        policy_sections, identity_sections = [], []
        for definitions, destination in [
            (self.POLICY_SECTIONS, policy_sections),
            (self.IDENTITY_SECTIONS, identity_sections),
        ]:
            for label, key in definitions:
                reasons = [
                    f'{side}: {reason}'
                    for side, snapshot in [('Left', left), ('Right', right)]
                    if (reason := self._unavailable_reason(snapshot, key, include_incomplete=include_incomplete))
                ]
                scope_key = (
                    'recursive'
                    if key == 'compartments' or definitions is self.POLICY_SECTIONS
                    else 'compartment_domain_search_depth'
                )
                if (
                    left.get(scope_key) is not None
                    and right.get(scope_key) is not None
                    and left[scope_key] != right[scope_key]
                ):
                    reasons.append(f'Load scope differs ({scope_key}).')
                if reasons:
                    skipped[label] = ' '.join(reasons)
                else:
                    incomplete_sides = [
                        side
                        for side, snapshot in [('Baseline', left), ('Target', right)]
                        if snapshot.get('inventory_complete') is False
                    ]
                    if incomplete_sides:
                        warnings[label] = (
                            ' and '.join(incomplete_sides) + ' collection is incomplete. '
                            'These are observed snapshot differences; missing records may reflect '
                            'collection gaps and are not confirmed OCI additions/deletions.'
                        )
                    destination.append(
                        self._compare_section(left, right, label=label, key=key, meaningful_only=meaningful_only)
                    )
        return HistoricalCompareResult(
            left_cache=left_name,
            right_cache=right_name,
            policy_sections=policy_sections,
            identity_sections=identity_sections,
            identity_comparable=not any(
                label in skipped for label, key in self.IDENTITY_SECTIONS if key != 'compartments'
            ),
            skipped_sections=skipped,
            section_warnings=warnings,
            metadata={
                'baseline': self.describe_snapshot(left),
                'target': self.describe_snapshot(right),
                'tenancy': right.get('tenancy_name') or left.get('tenancy_name') or '',
                'tenancy_verified': bool(left.get('tenancy_ocid') and right.get('tenancy_ocid')),
                'meaningful_only': meaningful_only,
                'include_incomplete': include_incomplete,
            },
        )
