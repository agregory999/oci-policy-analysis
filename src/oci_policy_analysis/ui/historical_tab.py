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
from tkinter import ttk

from deepdiff import DeepDiff

from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.ui.base_tab import BaseUITab

logger = get_logger('historical_tab')


class HistoricalTab(BaseUITab):
    """
    Tab for comparing two cached tenancy states using DeepDiff.

    Key Features / UI Layout:
    - Lets users select left and right (baseline/target) cache snapshots via dropdown.
    - Immediately below each dropdown, tenancy name, OCID, and data_as_of fields are displayed.
    - On comparison, runs a separate DeepDiff for each of:
        Top display (Policies):
          • Policies
          • Regular Statements
          • Defined Aliases
          • Cross-Tenancy Statements
        Bottom display (Identity):
          • Identity Domains
          • Groups
          • Dynamic Groups
          • Users
      Each section gets its own diff (not a path-grouped section from a single DeepDiff).
    - Info-level logging summarizes each diff result.
    - Results for each element type appear in a dedicated tree node, regardless of changes.
    - Keeps UI responsive by running diffs in a background thread.

    Inherits from BaseUITab for context/page help and uniform UI look.
    """

    def __init__(self, parent, caching, *args, **kwargs):
        # Default page help text (displayed at top)
        default_help = (
            'Compare cached tenancy states to find differences in policies, statements, users, groups, dynamic groups, and compartments. '
            "Select the left and right cache snapshots then click 'Compare'. "
            'Policy and identity changes will be organized for review below.'
        )
        super().__init__(
            parent,
            default_help_text=default_help,
            page_help_link='/usage.html#historical-comparison-tab',
        )
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
        """
        Constructs the UI controls for the Historical Comparison tab.

        Walkthrough:
        - Adds comboboxes for selecting left/right cached tenancy states.
        - "Compare" button starts the diff computation.
        - Adds context help for key widgets (see add_context_help usage).
        - Below, Treeview widgets are used to show grouped changes.
        - Status label gives progress or errors.
        """
        top = ttk.Frame(self)
        top.pack(fill='x', padx=6, pady=6)

        ttk.Label(top, text='Left Cache:').pack(side='left', padx=(0, 4))
        self.left_combo = ttk.Combobox(top, textvariable=self.left_cache_var, state='readonly', width=40)
        self.left_combo.pack(side='left', padx=(0, 10))
        # Context help for dropdown
        self.add_context_help(
            self.left_combo,
            "Select the cached tenancy state for the left side of the comparison (the 'before' or baseline).",
        )

        ttk.Label(top, text='Right Cache:').pack(side='left', padx=(0, 4))
        self.right_combo = ttk.Combobox(top, textvariable=self.right_cache_var, state='readonly', width=40)
        self.right_combo.pack(side='left', padx=(0, 10))
        self.add_context_help(
            self.right_combo,
            "Select the tenancy state for the right side of the comparison (the 'after', or what you're comparing against).",
        )

        # --- Tenancy info labels directly below dropdowns ---
        info_frame = ttk.Frame(self)
        info_frame.pack(fill='x', padx=6, pady=(0, 4))
        self.left_info_lbl = ttk.Label(info_frame, text='', anchor='w', justify='left', foreground='gray')
        self.left_info_lbl.pack(side='left', fill='x', expand=True, padx=(0, 12))
        self.right_info_lbl = ttk.Label(info_frame, text='', anchor='w', justify='left', foreground='gray')
        self.right_info_lbl.pack(side='left', fill='x', expand=True)

        # Attach trace to update cache info when dropdown selection changes
        self.left_cache_var.trace_add('write', lambda *a: self._update_cache_info('left'))
        self.right_cache_var.trace_add('write', lambda *a: self._update_cache_info('right'))

        compare_btn = ttk.Button(top, text='Compare', command=self._on_compare)
        compare_btn.pack(side='left', padx=(0, 10))
        self.add_context_help(
            compare_btn,
            'Compute the difference between the two selected tenancy state caches. Results are grouped below by Policy and by Identity top-level item.',
        )

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
        # Show initial tenancy info for the default dropdown values
        self._update_cache_info('left')
        self._update_cache_info('right')
        logger.info('HistoricalTab UI initialized.')

        # More context help can be added to key widgets in the trees if desired.
        # self.add_context_help(self.policy_tree, "Tree showing grouped policy changes between cache states.")
        # self.add_context_help(self.identity_tree, "Tree showing changes: first by compartment, then group/dynamic group/user.")

    # ------------------------------------------------------------------

    def _update_cache_info(self, side):
        """
        Show tenancy name, OCID, and data_as_of for selected cache, on the correct info label.
        """
        var = self.left_cache_var if side == 'left' else self.right_cache_var
        lbl = self.left_info_lbl if side == 'left' else self.right_info_lbl
        cache_name = var.get()
        if not cache_name:
            lbl.config(text='')
            return
        try:
            meta = self.caching.load_cache_into_local_json(cached_tenancy=cache_name)
            if not meta or not isinstance(meta, dict):
                lbl.config(text='')
                return
            tname = meta.get('tenancy_name', '') or meta.get('name', '')
            tocid = meta.get('tenancy_ocid', '')
            dasof = meta.get('data_as_of', '')
            new_txt = []
            if tname:
                new_txt.append(f'Tenancy: {tname}\n')
            if tocid:
                new_txt.append(f'OCID: {tocid}\n')
            if dasof:
                new_txt.append(f'As of: {dasof}')
            lbl.config(text=''.join(new_txt))
        except Exception as exc:
            lbl.config(text=f'Failed to load: {exc}')

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
        """
        Triggers a comparison between two selected cached tenancy states.
        Loads both caches, canonicalizes unordered content, and spawns a background thread (worker)
        to compute and organize diffs per required section (see class docstring for all categories).
        """
        left = self.left_cache_var.get()
        right = self.right_cache_var.get()
        if not left or not right:
            logger.warning('Both left and right caches must be selected before comparing.')
            return

        self._set_status('Running DeepDiff…', 'blue')
        logger.info(f"Starting DeepDiff between '{left}' and '{right}'.")

        try:
            # Step 1: Load both selected caches as parsed JSONable dicts
            self._left_data = self.caching.load_cache_into_local_json(cached_tenancy=left)
            self._right_data = self.caching.load_cache_into_local_json(cached_tenancy=right)
            if not self._left_data or not self._right_data:
                paths = [
                    getattr(self.caching, 'get_cache_path', lambda name: f'(cache path unavailable for {name})')(left),
                    getattr(self.caching, 'get_cache_path', lambda name: f'(cache path unavailable for {name})')(right),
                ]
                logger.error(
                    f'Cache load failed: One or both selected cache files could not be loaded.\nLeft: {paths[0]}\nRight: {paths[1]}'
                )
                self._set_status(
                    f'Error: One or both cache files could not be loaded.\nCheck local cache paths and file access:\nLeft: {paths[0]}\nRight: {paths[1]}',
                    'red',
                )
                return
            logger.debug('Successfully loaded both cache JSONs.')
        except Exception as exc:
            logger.error(f'Failed to load caches: {exc}')
            self._set_status(f'Cache load failed: {exc}\nCheck that both cache files exist and are readable.', 'red')
            return

        def worker():
            """
            Background thread for per-section comparison—prevents UI blocking.

            For each required top-level element of the policy and identity data, runs
            a DeepDiff on just that element (e.g. policies, policy_statements, domains, users, etc.)
            and logs results. Builds a dictionary for each display pane (policies/identity), passed
            to the display method for section-by-section reporting.

            Per-section diffs avoid cross-section noise and make the UI grouping direct and predictable.

            Maintains info-level logging for each element type.
            """
            start = time.time()
            try:
                # Step 2: Canonicalize unordered lists for robust comparison.
                logger.info(
                    'Filtering known unordered lists (policies/statements/defined_aliases/cross_tenancy_statements/domains/groups/dynamic_groups/users)...'
                )
                logger.debug(
                    'Skipping canonical_filter; running per-section DeepDiff on raw dict input (ignore_order=True).'
                )

                policy_sections_to_keys = [
                    ('Policies', 'policies'),
                    ('Regular Statements', 'policy_statements'),
                    ('Defined Aliases', 'defined_aliases'),
                    ('Cross-Tenancy Statements', 'cross_tenancy_statements'),
                ]
                identity_sections_to_keys = [
                    ('Identity Domains', 'domains'),
                    ('Groups', 'groups'),
                    ('Dynamic Groups', 'dynamic_groups'),
                    ('Users', 'users'),
                ]
                policy_diffs_by_section = {}
                identity_diffs_by_section = {}
                # Ignore 'internal_id' fields from statements in all lists:
                internal_id_exclude_regex = r"root\[\d+\]\['internal_id'\]"

                for label, key in policy_sections_to_keys:
                    lval = self._left_data.get(key, [])
                    rval = self._right_data.get(key, [])
                    diff = DeepDiff(
                        lval, rval, verbose_level=2, ignore_order=True, exclude_regex_paths=[internal_id_exclude_regex]
                    )
                    policy_diffs_by_section[label] = diff.to_dict()
                    logger.info(
                        f'DeepDiff for {label} [key={key}] completed. Diff types: {list(policy_diffs_by_section[label].keys())}; Count: {sum(len(v) if isinstance(v, dict) else 1 for v in policy_diffs_by_section[label].values())}'
                    )
                for label, key in identity_sections_to_keys:
                    lval = self._left_data.get(key, [])
                    rval = self._right_data.get(key, [])
                    diff = DeepDiff(
                        lval, rval, verbose_level=2, ignore_order=True, exclude_regex_paths=[internal_id_exclude_regex]
                    )
                    identity_diffs_by_section[label] = diff.to_dict()
                    logger.info(
                        f'DeepDiff for {label} [key={key}] completed. Diff types: {list(identity_diffs_by_section[label].keys())}; Count: {sum(len(v) if isinstance(v, dict) else 1 for v in identity_diffs_by_section[label].values())}'
                    )

                elapsed = time.time() - start

                # Step 5: Main thread callback for grouped display and status update
                self.after(0, lambda: self._display_grouped(policy_diffs_by_section, identity_diffs_by_section))
                self.after(0, lambda: self._set_status(f'Done in {elapsed:.2f}s.', 'green'))

            except Exception as exc:
                logger.error(f'DeepDiff worker error: {exc}')
                self.after(0, lambda: self._set_status('Diff failed.', 'red'))

        threading.Thread(target=worker, daemon=True).start()

    # # ------------------------------------------------------------------
    # def _filter_sections(self, diff_dict: dict, include_tokens: tuple[str, ...]) -> dict:
    #     filtered = {}
    #     for section, payload in diff_dict.items():
    #         if isinstance(payload, dict):
    #             kept = {p: v for p, v in payload.items() if any(tok in str(p) for tok in include_tokens)}
    #             if kept:
    #                 filtered[section] = kept
    #     logger.debug(f'Filtered {len(filtered)} items for tokens {include_tokens}.')
    #     return filtered

    # ------------------------------------------------------------------
    def _display_grouped(self, policy_sections: dict, identity_sections: dict):
        """
        Populate the policy and identity trees with grouped differences.

        Each policy and identity pane contains one explicit top-level group per required data element
        (section order matches requirements, e.g., "Policies", "Regular Statements", ..., "Identity Domains", ...).

        Each group's contents are produced by its dedicated DeepDiff, ensuring separation and correctness;
        this replaces the legacy grouped-path method.

        Each _populate_group_section call generates subnodes per modification/addition/removal as before.

        If no differences exist for any section, an explicit "No differences detected" message is shown.

        Logs the number of tree nodes for review.
        """
        # Clear both display trees
        for tree in (self.policy_tree, self.identity_tree):
            tree.delete(*tree.get_children())

        # Populate the policy section: show each as its own group even if no changes.
        for section in [
            'Policies',
            'Regular Statements',
            'Defined Aliases',
            'Cross-Tenancy Statements',
        ]:
            payload = policy_sections.get(section, {})
            self._populate_group_section(self.policy_tree, section, payload, is_policy=True)

        # Populate the identity section: show each as its own group even if no changes.
        identity_section_display = [
            'Identity Domains',
            'Groups',
            'Dynamic Groups',
            'Users',
        ]
        for section in identity_section_display:
            payload = identity_sections.get(section, {})
            self._populate_group_section(self.identity_tree, section, payload, is_policy=False)

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

    def _populate_group_section(self, tree: ttk.Treeview, section_title: str, deepdiff_subset: dict, is_policy: bool):  # noqa: C901
        """
        Populate a Treeview with grouped diff results. Simpler version: each diff shown as a node with its path and action label,
        value(s) as children. Uses section-based node titling for consistency and clarity.
        """
        import json

        logger.info(f'Populate section: {section_title} - diff keys: {list(deepdiff_subset.keys())}')
        total_entries = sum(len(v) for v in deepdiff_subset.values()) if deepdiff_subset else 0
        parent = tree.insert('', 'end', text=f'{section_title} ({total_entries})', open=False)
        if not deepdiff_subset or total_entries == 0:
            return

        # Helper: extract index and optionally a field from a DeepDiff "path" string
        def _extract_index_field(path):
            # Typical: "root[2]" or "root[3]['statement_text']"
            m = re.match(r"root\[(\d+)\](?:\['(.+)'\])?", path)
            if m:
                idx = int(m.group(1))
                field = m.group(2)
                return idx, field
            return None, None

        for diff_kind, entries in deepdiff_subset.items():
            for path, detail in entries.items():
                kind_map = {
                    'dictionary_item_added': 'Added',
                    'iterable_item_added': 'Added',
                    'dictionary_item_removed': 'Removed',
                    'iterable_item_removed': 'Removed',
                    'values_changed': 'Modified',
                }
                action = kind_map.get(diff_kind, diff_kind.title())

                # --- DEBUGGING: Log core details for each entry ---
                logger.debug(
                    f'[DiffNode] Section: {section_title} | Diff kind: {diff_kind} | Path: {path} | Action: {action}'
                )
                logger.debug(f'[DiffNode]   Detail type: {type(detail)} | Detail (truncated): {str(detail)[:512]}')

                # Try to extract a display title for this node
                idx, field = _extract_index_field(path)
                logger.debug(f'[DiffNode]   Extracted index: {idx} | Field: {field}')

                # Determine which list the index applies to
                obj = None
                source_list = None
                list_key = None
                try:
                    if section_title in [
                        'Policies',
                        'Regular Statements',
                        'Defined Aliases',
                        'Cross-Tenancy Statements',
                    ]:
                        list_key = {
                            'Policies': 'policies',
                            'Regular Statements': 'policy_statements',
                            'Defined Aliases': 'defined_aliases',
                            'Cross-Tenancy Statements': 'cross_tenancy_statements',
                        }[section_title]
                    else:
                        list_key = {
                            'Identity Domains': 'domains',
                            'Groups': 'groups',
                            'Dynamic Groups': 'dynamic_groups',
                            'Users': 'users',
                        }[section_title]
                    # Choose source list for lookup
                    side = 'right' if action == 'Added' else 'left'
                    logger.debug(f'[DiffNode]   List key: {list_key} | Data side: {side}')
                    if idx is not None:
                        if action == 'Added':
                            source_list = getattr(self, '_right_data', {}).get(list_key, [])
                        else:
                            source_list = getattr(self, '_left_data', {}).get(list_key, [])
                        logger.debug(
                            f"[DiffNode]   Source list type: {type(source_list)}, Length: {len(source_list) if isinstance(source_list, list) else '?'}"
                        )
                        if isinstance(source_list, list) and 0 <= idx < len(source_list):
                            obj = source_list[idx]
                    if obj:
                        logger.debug(f'[DiffNode]   Resolved object: {repr(obj)[:256]}')
                    else:
                        logger.debug(f'[DiffNode]   Could not resolve object at index {idx} in {side} list')
                except Exception as e:
                    logger.debug(f'[DiffNode]   Error retrieving object: {e}')
                    obj = None

                title = self._get_node_title(section_title, obj) if obj else None
                if title:
                    label = title
                    if field:
                        label += f' → {field}'
                    label += f' ({action})'
                else:
                    label = f'{path} ({action})'

                logger.debug(f'[DiffNode]   Final label: {label}')

                node = tree.insert(parent, 'end', text=label, open=False)
                # Show value details (unchanged from original)
                if isinstance(detail, dict) and 'old_value' in detail and 'new_value' in detail:
                    tree.insert(
                        node,
                        'end',
                        text=f"Old value: {json.dumps(detail['old_value'], indent=2, ensure_ascii=False) if isinstance(detail['old_value'], dict | list) else detail['old_value']}",
                    )
                    tree.insert(
                        node,
                        'end',
                        text=f"New value: {json.dumps(detail['new_value'], indent=2, ensure_ascii=False) if isinstance(detail['new_value'], dict | list) else detail['new_value']}",
                    )
                elif isinstance(detail, dict) and 'old_value' in detail:
                    tree.insert(
                        node,
                        'end',
                        text=f"Old value: {json.dumps(detail['old_value'], indent=2, ensure_ascii=False) if isinstance(detail['old_value'], dict | list) else detail['old_value']}",
                    )
                elif isinstance(detail, dict) and 'new_value' in detail:
                    tree.insert(
                        node,
                        'end',
                        text=f"New value: {json.dumps(detail['new_value'], indent=2, ensure_ascii=False) if isinstance(detail['new_value'], dict | list) else detail['new_value']}",
                    )
                elif isinstance(detail, dict):
                    for k, v in detail.items():
                        tree.insert(
                            node,
                            'end',
                            text=f'{k}: {json.dumps(v, indent=2, ensure_ascii=False) if isinstance(v, dict | list) else v}',
                        )
                else:
                    tree.insert(node, 'end', text=str(detail))

    # ------------------------------------------------------------------
    @staticmethod
    def _get_node_title(section_title: str, obj: dict) -> str | None:
        """
        Return a concise title string for a diff'd node, given its section and object dict.
        """
        if not obj or not isinstance(obj, dict):
            return None
        try:
            NODE_TITLE_FIELDS = {
                'Users': lambda o: f"{o.get('domain_name','')}/{o.get('user_name','')}"
                if o.get('domain_name')
                else o.get('user_name', ''),
                'Groups': lambda o: f"{o.get('domain_name','')}/{o.get('group_name','')}"
                if o.get('domain_name')
                else o.get('group_name', ''),
                'Dynamic Groups': lambda o: o.get('dynamic_group_name', ''),
                'Policies': lambda o: o.get('policy_name', ''),
                'Defined Aliases': lambda o: f"{o.get('policy_name','')}/{o.get('defined_type','')}/{o.get('defined_name','')}",
                'Regular Statements': lambda o: f"{o.get('compartment_path','')}/{o.get('policy_name','')}",
                # Add more as needed:
                'Identity Domains': lambda o: o.get('name', ''),
                'Cross-Tenancy Statements': lambda o: o.get('policy_name', ''),  # fallback
            }
            fn = NODE_TITLE_FIELDS.get(section_title)
            title = fn(obj) if fn else None
            # Clean up, remove leading/trailing slashes if any field is missing
            if title:
                title = title.strip('/')
            return title if title else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    def _set_status(self, text: str, color: str = ''):
        self.status_var.set(text)
        try:
            self.status_lbl.configure(foreground=color if color else '')
        except Exception:
            pass
