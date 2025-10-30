##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# historical_tab.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

import re
import threading
import time
import tkinter as tk
from collections import defaultdict
from tkinter import ttk
from typing import Any

from deepdiff import DeepDiff

from oci_policy_analysis.logger import get_logger

logger = get_logger('oci-policy-analysis.historical_tab')


class HistoricalTab(ttk.Frame):
    def __init__(self, parent, caching, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.caching = caching
        self.left_cache_var = tk.StringVar()
        self.right_cache_var = tk.StringVar()
        self._left_data = None
        self._right_data = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI Setup
    # ------------------------------------------------------------------
    def _build_ui(self):
        top = ttk.Frame(self)
        top.pack(fill='x', padx=6, pady=6)

        ttk.Label(top, text='Left Cache:').pack(side='left', padx=(0, 4))
        self.left_combo = ttk.Combobox(top, textvariable=self.left_cache_var, state='readonly', width=40)
        self.left_combo.pack(side='left', padx=(0, 10))

        ttk.Label(top, text='Right Cache:').pack(side='left', padx=(0, 4))
        self.right_combo = ttk.Combobox(top, textvariable=self.right_cache_var, state='readonly', width=40)
        self.right_combo.pack(side='left', padx=(0, 10))

        ttk.Button(top, text='Compare', command=self._on_compare).pack(side='left', padx=(0, 10))

        self.status_var = tk.StringVar(value='')
        self.status_lbl = ttk.Label(self, textvariable=self.status_var)
        self.status_lbl.pack(fill='x', padx=6, pady=(0, 4))

        ttk.Label(self, text='Policy Changes', font=('TkDefaultFont', 10, 'bold')).pack(fill='x', padx=6, pady=(2, 0))
        self.policy_tree = ttk.Treeview(self, height=10)
        self.policy_tree.heading('#0', text='Policies / Statements', anchor='w')
        self.policy_tree.pack(fill='both', expand=True, padx=6, pady=(0, 6))

        ttk.Label(self, text='Identity & Compartments', font=('TkDefaultFont', 10, 'bold')).pack(
            fill='x', padx=6, pady=(4, 0)
        )
        self.identity_tree = ttk.Treeview(self, height=8)
        self.identity_tree.heading('#0', text='Users / Groups / Dynamic Groups / Compartments', anchor='w')
        self.identity_tree.pack(fill='both', expand=True, padx=6, pady=(0, 6))

        self.populate_cache_dropdowns()
        logger.info('HistoricalTab UI initialized.')

    # ------------------------------------------------------------------
    def populate_cache_dropdowns(self, tenancy_name=None):
        try:
            caches = self.caching.get_available_cache(tenancy_name=tenancy_name)
            self.left_combo['values'] = caches
            self.right_combo['values'] = caches
            if caches:
                self.left_cache_var.set(caches[0])
                self.right_cache_var.set(caches[-1])
            logger.info(f'Loaded {len(caches)} available caches for dropdowns.')
        except Exception as exc:
            logger.error(f'Failed to populate cache list: {exc}')

    # ------------------------------------------------------------------

    def _on_compare(self):
        left = self.left_cache_var.get()
        right = self.right_cache_var.get()
        if not left or not right:
            logger.warning('Both left and right caches must be selected before comparing.')
            return

        self._set_status('Running DeepDiff…', 'blue')
        logger.info(f"Starting DeepDiff between '{left}' and '{right}'.")

        try:
            self._left_data = self.caching.load_cache_into_local_json(cached_tenancy=left)
            self._right_data = self.caching.load_cache_into_local_json(cached_tenancy=right)
            logger.debug('Successfully loaded both cache JSONs.')
        except Exception as exc:
            logger.error(f'Failed to load caches: {exc}')
            self._set_status('Cache load failed.', 'red')
            return

        def worker():
            start = time.time()
            try:
                logger.info(
                    'Filtering known unordered lists (policies/statements/users/groups/dynamic_groups/compartments)...'
                )
                left_filtered = self._filter_for_comparison(self._left_data)
                right_filtered = self._filter_for_comparison(self._right_data)

                logger.debug('Canonicalization complete; starting DeepDiff (ignore_order=False).')

                diff = DeepDiff(left_filtered, right_filtered, verbose_level=2, ignore_order=True)
                diff_dict = diff.to_dict()
                elapsed = time.time() - start
                logger.info(f'DeepDiff completed in {elapsed:.2f}s with keys: {list(diff_dict.keys())}')

                policy_sections = {
                    'Policies': self._filter_sections(diff_dict, ("['policies']", "['policy_statements']")),
                    'Cross-Tenancy Statements': self._filter_sections(diff_dict, ("['cross_tenancy_statements']",)),
                }
                identity_sections = {
                    'Users': self._filter_sections(diff_dict, ("['users']",)),
                    'Groups': self._filter_sections(diff_dict, ("['groups']",)),
                    'Dynamic Groups': self._filter_sections(diff_dict, ("['dynamic_groups']",)),
                    'Compartments': self._filter_sections(diff_dict, ("['compartments']",)),
                }

                logger.debug(
                    "Section sizes -> "
                    f"Policies={sum(len(v) for v in policy_sections['Policies'].values())}, "
                    f"CrossTenancy={sum(len(v) for v in policy_sections['Cross-Tenancy Statements'].values())}, "
                    f"Users={sum(len(v) for v in identity_sections['Users'].values())}, "
                    f"Groups={sum(len(v) for v in identity_sections['Groups'].values())}, "
                    f"DynamicGroups={sum(len(v) for v in identity_sections['Dynamic Groups'].values())}, "
                    f"Compartments={sum(len(v) for v in identity_sections['Compartments'].values())}"
                )

                self.after(0, lambda: self._display_grouped(policy_sections, identity_sections))
                self.after(0, lambda: self._set_status(f'Done in {elapsed:.2f}s.', 'green'))

            except Exception as exc:
                logger.error(f'DeepDiff worker error: {exc}')
                self.after(0, lambda: self._set_status('Diff failed.', 'red'))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    def _filter_sections(self, diff_dict: dict, include_tokens: tuple[str, ...]) -> dict:
        filtered = {}
        for section, payload in diff_dict.items():
            if isinstance(payload, dict):
                kept = {p: v for p, v in payload.items() if any(tok in str(p) for tok in include_tokens)}
                if kept:
                    filtered[section] = kept
        logger.debug(f'Filtered {len(filtered)} items for tokens {include_tokens}.')
        return filtered

    # ------------------------------------------------------------------
    def _display_grouped(self, policy_sections: dict, identity_sections: dict):
        """Populate both policy and identity trees with grouped differences."""
        for tree in (self.policy_tree, self.identity_tree):
            tree.delete(*tree.get_children())

        # Populate policy and identity sections
        for title, payload in policy_sections.items():
            self._populate_group_section(self.policy_tree, title, payload, is_policy=True)
        for title, payload in identity_sections.items():
            self._populate_group_section(self.identity_tree, title, payload, is_policy=False)

        # No differences detected — show explicit message in both trees
        if not self.policy_tree.get_children() and not self.identity_tree.get_children():
            self.policy_tree.insert('', 'end', text='No differences detected.')
            self.identity_tree.insert('', 'end', text='No differences detected.')
            self._set_status('No relevant differences found.', 'green')
            logger.info('No differences detected.')
        else:
            logger.info(
                f'Displayed differences: {len(self.policy_tree.get_children())} policy nodes, '
                f'{len(self.identity_tree.get_children())} identity nodes.'
            )

    # ------------------------------------------------------------------
    def _filter_for_comparison(self, obj: Any) -> Any:
        """
        Reduce large OCI structures to only the relevant fields before diffing.
        Keeps only semantically meaningful keys to avoid noise and performance hits.
        """
        if isinstance(obj, list):
            return [self._filter_for_comparison(x) for x in obj]

        if isinstance(obj, dict):
            # Policy-like objects
            if 'policy_name' in obj or 'statement_text' in obj:
                return {
                    k: obj.get(k)
                    for k in (
                        'policy_name',
                        'statement_text',
                        'compartment_name',
                        'valid',
                        'invalid',
                        'invalid_reasons',
                    )
                    if k in obj
                }

            # Identity (user/group/dynamic_group)
            if any(k in obj for k in ('user_name', 'group_name', 'dynamic_group_name')):
                return {
                    k: obj.get(k)
                    for k in ('domain_name', 'user_name', 'group_name', 'dynamic_group_name', 'groups')
                    if k in obj
                }

            # Compartments
            if 'hierarchy_path' in obj:
                return {k: obj.get(k) for k in ('id', 'name', 'hierarchy_path', 'parent_id') if k in obj}

            # Generic dict — recurse
            return {k: self._filter_for_comparison(v) for k, v in obj.items()}

        # Primitives
        return obj

    def _populate_group_section(self, tree: ttk.Treeview, section_title: str, deepdiff_subset: dict, is_policy: bool):
        if not deepdiff_subset:
            return

        total_entries = sum(len(v) for v in deepdiff_subset.values())
        parent = tree.insert('', 'end', text=f'{section_title} ({total_entries})', open=False)
        logger.debug(f"Populating section '{section_title}' with {total_entries} entries.")

        grouped = defaultdict(list) if is_policy else None

        for diff_kind, entries in deepdiff_subset.items():
            for path, detail in entries.items():
                if is_policy:
                    policy_name = self._extract_policy_name_from_path(path)
                    grouped[policy_name].append((diff_kind, path, detail))
                else:
                    self._insert_entity_node(tree, parent, diff_kind, path, detail, is_policy=False)

        if is_policy:
            for policy_name, items in grouped.items():
                kinds = {k for k, _, _ in items}
                added_kinds = {'dictionary_item_added', 'iterable_item_added'}
                removed_kinds = {'dictionary_item_removed', 'iterable_item_removed'}
                if kinds and kinds.issubset(added_kinds):
                    policy_status = 'Added'
                elif kinds and kinds.issubset(removed_kinds):
                    policy_status = 'Removed'
                else:
                    policy_status = 'Modified'

                policy_label = f"{policy_name or '(unknown policy)'} ({policy_status})"
                policy_node = tree.insert(parent, 'end', text=policy_label, open=False)

                for diff_kind, path, detail in items:
                    self._insert_entity_node(tree, policy_node, diff_kind, path, detail, is_policy=True)

    # ------------------------------------------------------------------
    def _insert_entity_node(self, tree, parent, diff_kind, path, detail, is_policy):  # noqa: C901
        label, status = self._label_for_entry(path, detail, is_policy, diff_kind)
        node = tree.insert(parent, 'end', text=label, open=False)

        if status.startswith('Field '):
            field_name_match = re.findall(r"\['([^']+)'\]$", str(path))
            field_name = field_name_match[-1] if field_name_match else '(unknown field)'

            # Handle both dict and primitive detail types
            old_val = None
            new_val = None
            if isinstance(detail, dict):
                old_val = detail.get('old_value')
                new_val = detail.get('new_value')
            else:
                # For iterable_item_removed/added, DeepDiff gives value directly
                if 'Removed' in status:
                    old_val = detail
                elif 'Added' in status:
                    new_val = detail

            if 'Modified' in status and old_val is not None and new_val is not None:
                tree.insert(node, 'end', text=f'{field_name}: {old_val} → {new_val}')
            elif 'Added' in status and new_val is not None:
                tree.insert(node, 'end', text=f'{field_name}: {new_val}')
            elif 'Removed' in status and old_val is not None:
                tree.insert(node, 'end', text=f'{field_name}: {old_val}')
            logger.debug(f'Inserted field-level change: {field_name} ({status}) -> old={old_val}, new={new_val}')
            return
        if status == 'Modified' and isinstance(detail, dict) and 'old_value' in detail and 'new_value' in detail:
            tree.insert(node, 'end', text=f"Old: {detail['old_value']}")
            tree.insert(node, 'end', text=f"New: {detail['new_value']}")
        elif status in ('Added', 'Removed'):
            base = self._right_data if status == 'Added' else self._left_data
            obj = self._get_enclosing_object_for_path(base, str(path), is_policy=is_policy)
            if isinstance(obj, dict):
                for k, v in sorted(obj.items()):
                    tree.insert(node, 'end', text=f'{k}: {v}')
            else:
                resolved = self._resolve_path(base, str(path))
                tree.insert(node, 'end', text=f'value: {resolved}')
        logger.debug(f'Inserted entity node: {label} ({status}).')

    # ------------------------------------------------------------------
    def _label_for_entry(
        self, path: str, detail: Any, is_policy: bool, diff_kind: str | None = None
    ) -> tuple[str, str]:
        path_str = str(path)
        status_map = {
            'dictionary_item_added': 'Added',
            'iterable_item_added': 'Added',
            'dictionary_item_removed': 'Removed',
            'iterable_item_removed': 'Removed',
            'values_changed': 'Modified',
        }
        status = status_map.get(diff_kind, 'Modified')

        m = re.findall(r"\['([^']+)'\]$", path_str)
        field_name = m[-1] if m else None

        if is_policy:
            base = self._right_data if status in ('Added', 'Modified') else self._left_data
            policy = self._find_enclosing(base, path_str, 'policy_name')
            stmt = self._find_enclosing(base, path_str, 'statement_text')
            policy_name = policy.get('policy_name') if isinstance(policy, dict) else None
            statement_text = (
                stmt.get('statement_text') if isinstance(stmt, dict) else (stmt if isinstance(stmt, str) else None)
            )

            label_parts = []
            if policy_name:
                label_parts.append(policy_name)
            if statement_text:
                label_parts.append(statement_text)

            if field_name and field_name not in ('statement_text', 'policy_name'):
                status = f'Field {status}'

            label = ': '.join(label_parts) if label_parts else path_str
            label += f' ({status})'
            return label, status

        base = self._right_data if status in ('Added', 'Modified') else self._left_data
        for section, key in (
            ("['users']", 'user_name'),
            ("['groups']", 'group_name'),
            ("['dynamic_groups']", 'dynamic_group_name'),
            ("['compartments']", 'name'),
        ):
            if section in path_str:
                obj = self._find_enclosing(base, path_str, key)
                if isinstance(obj, dict):
                    if section == "['compartments']":
                        label = obj.get('hierarchy_path') or obj.get('name')
                    else:
                        name = obj.get(key)
                        domain = obj.get('domain_name', 'Default')
                        label = f'{domain} / {name}' if domain and name else (name or domain or '?')
                    if field_name and field_name not in (key, 'domain_name'):
                        status = f'Field {status}'
                    label += f' ({status})'
                    return label, status

        return path_str, status

    # ------------------------------------------------------------------
    def _extract_policy_name_from_path(self, path: str) -> str | None:
        for base in (self._right_data, self._left_data):
            if base is None:
                continue
            obj = self._find_enclosing(base, str(path), 'policy_name')
            if isinstance(obj, dict) and 'policy_name' in obj:
                return obj.get('policy_name')
        return None

    # ------------------------------------------------------------------
    def _find_enclosing(self, base: Any, path_str: str, key: str) -> Any:
        target, found = base, None
        for is_index, token in self._iter_path_tokens(path_str):
            try:
                target = target[int(token)] if is_index else target[token]
            except Exception:
                break
            if isinstance(target, dict) and key in target:
                found = target
        return found

    def _resolve_path(self, base: Any, path_str: str) -> Any:
        target = base
        for is_index, token in self._iter_path_tokens(path_str):
            if target is None:
                return None
            try:
                target = target[int(token)] if is_index else target[token]
            except Exception:
                return None
        return target

    def _iter_path_tokens(self, path_str: str):
        for m in re.finditer(r"\[(\d+)\]|\['([^']+)'\]", path_str):
            idx, key = m.groups()
            yield (True, idx) if idx is not None else (False, key)

    # ------------------------------------------------------------------
    def _get_enclosing_object_for_path(self, base: Any, path_str: str, *, is_policy: bool) -> Any:
        for key in ['policy_name', 'statement_text', 'user_name', 'group_name', 'dynamic_group_name', 'name']:
            found = self._find_enclosing(base, path_str, key)
            if isinstance(found, dict):
                return found
        return self._resolve_path(base, path_str)

    # ------------------------------------------------------------------
    def _set_status(self, text: str, color: str = ''):
        self.status_var.set(text)
        try:
            self.status_lbl.configure(foreground=color if color else '')
        except Exception:
            pass
