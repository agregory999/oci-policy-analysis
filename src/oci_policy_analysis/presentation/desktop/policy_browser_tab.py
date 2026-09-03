##########################################################################
# Copyright (c) 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It is not supported by Oracle Support.
#
# policy_browser_tab.py
#
# @author: Andrew Gregory / Cline
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

import tkinter as tk
import tkinter.messagebox as tkmessagebox
from tkinter import ttk
from typing import Any

from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.presentation.desktop.base_tab import BaseUITab

logger = get_logger('policy_browser_tab')


class PolicyBrowserTab(BaseUITab):
    """
    Tab for browsing all compartments, policies, and policy statements in a JSON-style tree.
    Hierarchy: compartments → policies → statements (with statement text).
    No filtering or distinction of policy type; all statements appear under their policy.
    """

    def __init__(self, parent, app, settings):
        super().__init__(
            parent,
            default_help_text=(
                'Browse the policy inventory across all compartments, policies, and policy statements. '
                'Tree expands to reveal policies in each compartment and all their statement text. '
                'Right-click a policy or statement for navigation or actions.'
            ),
            page_help_link='/usage.html#policy-browser-tab',
        )
        self.app = app
        self.settings = settings
        self.policy_repo = app.policy_compartment_analysis
        self._data_initialized = False
        self._build_ui()

    def _build_ui(self):
        logger.info('Building UI for Policy Browser Tab')
        # Parent is a ttk.Notebook tab (self). Force this Frame to expand!
        self.pack(fill='both', expand=True)
        logger.info(
            f'self.winfo_class={self.winfo_class()} is mapped: {self.winfo_ismapped()}, size: {self.winfo_width()}x{self.winfo_height()}'
        )

        # --- Display Options LabelFrame with buttons ---
        display_frame = ttk.LabelFrame(self, text='Display Options')
        display_frame.pack(fill='x', expand=False, padx=10, pady=5)
        # Search, Expand/Collapse Button Row (packed inside new label frame)
        self.button_row = ttk.Frame(display_frame)
        self.button_row.pack(fill='x', expand=False, padx=0, pady=0)
        # --- Button/Entry/Labelling UI (reordered per feedback) ---
        expand_all_btn = ttk.Button(
            self.button_row, text='Expand All', command=lambda: self.expand_collapse_all(expand=True)
        )
        expand_all_btn.pack(side='left', padx=(0, 3))
        self.add_context_help(expand_all_btn, 'Expand all nodes in the tree.')

        collapse_all_btn = ttk.Button(
            self.button_row, text='Collapse All', command=lambda: self.expand_collapse_all(expand=False)
        )
        collapse_all_btn.pack(side='left', padx=(0, 3))
        self.add_context_help(collapse_all_btn, 'Collapse all nodes in the tree.')

        expand_comp_btn = ttk.Button(
            self.button_row,
            text='Expand Compartments Only',
            command=lambda: self.expand_collapse_compartments(only=True, expand=True),
        )
        expand_comp_btn.pack(side='left', padx=(8, 3))
        self.add_context_help(expand_comp_btn, 'Expand compartments only, collapse all policies/statements under them.')

        # Vertical separator for clarity
        sep = ttk.Separator(self.button_row, orient='vertical')
        sep.pack(side='left', fill='y', padx=(8, 8), pady=3)

        # Label for text search, then live search box, then clear button
        search_label = ttk.Label(self.button_row, text='Search:')
        search_label.pack(side='left', padx=(0, 2), pady=2)

        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(self.button_row, textvariable=self.search_var, width=32)
        search_entry.pack(side='left', padx=(0, 4), pady=2)

        clear_btn = ttk.Button(self.button_row, text='Clear', command=self.on_clear_search)
        clear_btn.pack(side='left', padx=(0, 3), pady=2)

        # Policy data belongs beside search because it changes the tree detail,
        # not the navigation controls to its left.
        self.show_policy_data_var = tk.BooleanVar(value=False)
        show_policy_data_chk = ttk.Checkbutton(
            self.button_row,
            text='Show Policy Data',
            variable=self.show_policy_data_var,
            command=self._toggle_policy_data,
        )
        show_policy_data_chk.pack(side='left', padx=(8, 8), pady=2)
        self.add_context_help(
            show_policy_data_chk,
            'Show policy statement counts in the tree and tenancy-specific policy limits. For cached or CIS data, enter limits here when OCI cannot fetch them.',
        )

        self.add_context_help(
            search_entry,
            'Type to search compartments, policies, statements, or tags (case-insensitive). Filtering occurs as you type.',
        )
        self.add_context_help(
            search_label,
            'Live text search for compartments, policies, statements, and tags. All containing/hierarchical nodes will be shown, results highlighted.',
        )
        self.add_context_help(
            clear_btn,
            'Reset the search and show all compartments, policies, and statements.',
        )

        self.policy_data_frame = ttk.Frame(display_frame)
        self.policy_data_summary_var = tk.StringVar()
        ttk.Label(self.policy_data_frame, textvariable=self.policy_data_summary_var).pack(side='left', padx=(0, 8))
        self.user_policy_limit_var = tk.StringVar()
        self.user_chain_limit_var = tk.StringVar()
        self.policy_limit_input_frame = ttk.Frame(self.policy_data_frame)
        ttk.Label(self.policy_limit_input_frame, text='policies-count:').pack(side='left', padx=(0, 2))
        ttk.Entry(self.policy_limit_input_frame, textvariable=self.user_policy_limit_var, width=7).pack(side='left')
        ttk.Label(self.policy_limit_input_frame, text='chain count:').pack(side='left', padx=(5, 2))
        ttk.Entry(self.policy_limit_input_frame, textvariable=self.user_chain_limit_var, width=7).pack(side='left')
        ttk.Button(self.policy_limit_input_frame, text='Apply limits', command=self._apply_user_supplied_limits).pack(
            side='left', padx=(4, 0)
        )

        # OCI GenAI controls are an opt-in desktop preview.
        if self.is_genai_feature_enabled():
            self.ai_assist_btn = ttk.Button(self.button_row, text='AI Assist', command=self._on_ai_assist_clicked)
            self.add_context_help(
                self.ai_assist_btn,
                'Show or hide the AI Assistant pane below to analyze policies.\nNOTE: AI must be enabled in Settings Tab and only policy statements are supported.',
            )
            self.ai_assist_btn.pack(side='left', padx=(14, 2), pady=2)
            self.ai_assist_btn.config(state=tk.DISABLED)

        # --- Reload Compartment / Policy Data Button ---
        self.btn_reload_policies = ttk.Button(
            self.button_row,
            text='Reload Compartment / Policy Data',
            command=self._handle_reload_policies,
        )
        # Add help and pack far right (side='right')
        self.add_context_help(
            self.btn_reload_policies,
            (
                'Reload policies and compartment data directly from tenancy (using original authentication and recursion settings).\n'
                'Enabled only if current data was loaded from tenancy, not cache/compliance. IAM group, Dynamic Group, and User data are NOT reloaded.'
            ),
        )
        self.btn_reload_policies.pack(side='right', padx=(16, 0), pady=2)
        # Set initial enabled state
        self._update_reload_policy_button_state()

        # Live search via Var trace
        self.search_var.trace_add('write', lambda *args: self.on_search())

        logger.info('Expand/collapse/search/clear buttons and entry added to Policy Browser tab UI.')

        # --- Main content area: left = policy tree (75%), right = tag namespaces (25%) ---
        content_frame = ttk.Frame(self)
        content_frame.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        content_frame.columnconfigure(0, weight=4)
        content_frame.columnconfigure(1, weight=1)
        content_frame.rowconfigure(0, weight=1)

        label_frm_tree = ttk.LabelFrame(content_frame, text='Compartment / Policy / Statement Tree', borderwidth=5)
        label_frm_tree.grid(row=0, column=0, sticky='nsew', padx=(0, 8), pady=0)
        logger.debug(
            f'label_frm_tree.winfo_class={label_frm_tree.winfo_class()} is mapped: {label_frm_tree.winfo_ismapped()}, size: {label_frm_tree.winfo_width()}x{label_frm_tree.winfo_height()}'
        )

        # Tree widget for the browser — give it a visible border (relief)
        self.tree = ttk.Treeview(label_frm_tree, show='tree')
        self.tree.pack(fill='both', expand=True, side='top', padx=2, pady=2)
        self.tree.configure(style='Treeview')
        # Configure tags for background coloring
        self.tree.tag_configure('bg_green', background='#d7ffd7')  # light green
        self.tree.tag_configure('bg_yellow', background='#fffcc7')  # light yellow
        self.tree.tag_configure('bg_red', background='#ffd7d7')  # light red
        logger.info(
            f'Treeview created: is mapped: {self.tree.winfo_ismapped()}, size: {self.tree.winfo_width()}x{self.tree.winfo_height()}'
        )

        self.tree.heading('#0', text='OCI Compartments → Policies → Statements', anchor='w')
        self.add_context_help(
            self.tree,
            'This tree shows the full compartment hierarchy with all OCI policies underneath. Expand compartments to view their policies and each statement. Right-click for actions.',
        )

        # Initial placeholder until the app calls post-load update.
        self.tree.insert('', 'end', text='Load tenancy/cache/compliance data from Settings to populate this tree.')

        # --- Defined Tag Namespace/Key catalog (from currently loaded data) ---
        tag_catalog_frame = ttk.LabelFrame(content_frame, text='Defined Tag Namespaces and Keys (Collected Data)')
        tag_catalog_frame.grid(row=0, column=1, sticky='nsew', padx=(0, 0), pady=0)
        self.add_context_help(
            tag_catalog_frame,
            'Shows currently discovered defined tag namespaces and keys from the loaded repository data. '
            'This is a read-only view to help browsing for now.',
        )

        tag_toolbar = ttk.Frame(tag_catalog_frame)
        tag_toolbar.pack(fill='x', padx=6, pady=(4, 2))

        refresh_tag_catalog_btn = ttk.Button(
            tag_toolbar,
            text='Refresh Tag Catalog',
            command=self._refresh_tag_catalog_display,
        )
        refresh_tag_catalog_btn.pack(side='left', padx=(0, 6))
        self.add_context_help(
            refresh_tag_catalog_btn,
            'Rebuild the namespace/key list from currently loaded policies.',
        )

        self.tag_catalog_summary_var = tk.StringVar(
            value='No loaded data yet. Tag namespaces will appear after tenancy/cache/compliance load.'
        )
        ttk.Label(tag_toolbar, textvariable=self.tag_catalog_summary_var).pack(side='left', padx=(4, 0))

        # Top table (about 70%): namespace/key rows (no values column).
        self.tag_catalog_tree = ttk.Treeview(
            tag_catalog_frame,
            columns=('Namespace', 'Compartment Path', 'Defined Key'),
            show='headings',
            height=12,
        )
        self.tag_catalog_tree.heading('Namespace', text='Namespace', anchor='w')
        self.tag_catalog_tree.heading('Compartment Path', text='Compartment Path', anchor='w')
        self.tag_catalog_tree.heading('Defined Key', text='Defined Key', anchor='w')
        # Keep requested width small so this pane can shrink gracefully on narrow windows.
        self.tag_catalog_tree.column('Namespace', width=120, minwidth=90, anchor='w', stretch=True)
        self.tag_catalog_tree.column('Compartment Path', width=160, minwidth=110, anchor='w', stretch=True)
        self.tag_catalog_tree.column('Defined Key', width=120, minwidth=90, anchor='w', stretch=True)
        self.tag_catalog_tree.pack(fill='both', expand=True, padx=6, pady=(0, 4))

        tag_vsb = ttk.Scrollbar(tag_catalog_frame, orient='vertical', command=self.tag_catalog_tree.yview)
        tag_hsb = ttk.Scrollbar(tag_catalog_frame, orient='horizontal', command=self.tag_catalog_tree.xview)
        self.tag_catalog_tree.configure(yscrollcommand=tag_vsb.set, xscrollcommand=tag_hsb.set)
        tag_vsb.place(in_=self.tag_catalog_tree, relx=1.0, rely=0, relheight=1.0, anchor='ne')
        tag_hsb.pack(fill='x', padx=6, pady=(0, 4))

        # Bottom table (~30%): value details for selected namespace/key row.
        value_label = ttk.Label(tag_catalog_frame, text='Values for selected namespace/key:')
        value_label.pack(fill='x', padx=6, pady=(2, 2))
        self.tag_catalog_values_tree = ttk.Treeview(
            tag_catalog_frame,
            columns=('Value',),
            show='headings',
            height=6,
        )
        self.tag_catalog_values_tree.heading('Value', text='Value', anchor='w')
        self.tag_catalog_values_tree.column('Value', width=320, minwidth=120, anchor='w', stretch=True)
        self.tag_catalog_values_tree.pack(fill='both', expand=False, padx=6, pady=(0, 6))

        value_vsb = ttk.Scrollbar(tag_catalog_frame, orient='vertical', command=self.tag_catalog_values_tree.yview)
        self.tag_catalog_values_tree.configure(yscrollcommand=value_vsb.set)
        value_vsb.place(in_=self.tag_catalog_values_tree, relx=1.0, rely=0, relheight=1.0, anchor='ne')

        # Metadata for top-row selection -> value detail rendering.
        self._tag_catalog_top_row_meta: dict[str, dict[str, Any]] = {}

        # Right-click context menu on tag catalog rows (cross-platform).
        self.tag_catalog_tree.bind('<Button-3>', self._on_tag_catalog_right_click)  # Right-click (Win/Linux)
        self.tag_catalog_tree.bind('<Button-2>', self._on_tag_catalog_right_click)  # Middle-click (some mac setups)
        self.tag_catalog_tree.bind('<Control-Button-1>', self._on_tag_catalog_right_click)  # Ctrl+Click (mac legacy)
        self.tag_catalog_tree.bind('<<TreeviewSelect>>', self._on_tag_catalog_selection_changed)
        self.tag_catalog_values_tree.bind('<Button-3>', self._on_tag_catalog_right_click)
        self.tag_catalog_values_tree.bind('<Button-2>', self._on_tag_catalog_right_click)
        self.tag_catalog_values_tree.bind('<Control-Button-1>', self._on_tag_catalog_right_click)

        logger.info('Finished _build_ui; Policy Browser widgets constructed (data population deferred).')
        # Bind context menu for universal cross-platform support
        self.tree.bind('<Button-3>', self._on_right_click)  # Right-click (Win/Linux)
        self.tree.bind('<Button-2>', self._on_right_click)  # Middle-click (Control+Click on Mac, some setups)
        self.tree.bind('<Control-Button-1>', self._on_right_click)  # Ctrl+Click (Mac legacy)
        # Bind item selection in tree to propagate selected statement for AI
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)

    def _update_reload_policy_button_state(self):
        """Enable or disable the reload button depending on whether reload is allowed."""
        allowed = False
        repo = getattr(self, 'policy_repo', None)
        if (
            repo
            and getattr(repo, 'policies_loaded_from_tenancy', False)
            and not getattr(repo, 'loaded_from_compliance_output', False)
        ):
            allowed = True
        if hasattr(self, 'btn_reload_policies'):
            if allowed:
                self.btn_reload_policies['state'] = tk.NORMAL
            else:
                self.btn_reload_policies['state'] = tk.DISABLED

    def _handle_reload_policies(self):
        """Handler for Reload Compartment / Policy Data button. Delegates actual reload+cache+UI to App."""
        repo = getattr(self, 'policy_repo', None)
        if not getattr(repo, 'policies_loaded_from_tenancy', False) or getattr(
            repo, 'loaded_from_compliance_output', False
        ):
            try:
                tkmessagebox.showwarning(
                    'Not allowed',
                    'Policy data can only be reloaded from tenancy (not cache/compliance). Please load from tenancy first.',
                )
            except Exception:
                pass
            self._update_reload_policy_button_state()
            return
        if hasattr(self.app, 'reload_policies_and_compartments_and_update_cache_async'):
            self.app.reload_policies_and_compartments_and_update_cache_async(
                callback={
                    'complete': lambda success, message, is_error: (
                        self._update_reload_policy_button_state(),
                        self.refresh_tree(),
                        logger.info('Policy reload completion: success=%s message=%s', success, message),
                    )
                },
                show_popup=True,
            )
            return

        try:
            self.configure(cursor='watch')
            self.update_idletasks()
            ok = False
            if hasattr(self.app, 'reload_policies_and_compartments_and_update_cache'):
                ok = self.app.reload_policies_and_compartments_and_update_cache()
            self.configure(cursor='')
            if ok:
                try:
                    tkmessagebox.showinfo(
                        'Policy Data Reloaded', 'Policies and compartments have been reloaded from tenancy.'
                    )
                except Exception:
                    pass
            else:
                self._update_reload_policy_button_state()
                tkmessagebox.showerror(
                    'Reload Failed',
                    'Policy data reload from tenancy failed. See application logs for details.',
                )
        except Exception as e:
            self.configure(cursor='')
            self._update_reload_policy_button_state()
            tkmessagebox.showerror('Reload Failed', f'Reload failed due to error: {str(e)}')

    def _ai_btn_is_packed(self):
        # Helper: return True if the AI Assist button is packed in the button row
        return bool(getattr(self, 'ai_assist_btn', None) and self.ai_assist_btn.winfo_ismapped())

    def _on_ai_assist_clicked(self):
        """Callback for AI Assist button. Toggles the AI (bottom) pane."""
        if self.is_genai_feature_enabled() and hasattr(self.app, 'toggle_bottom'):
            self.app.toggle_bottom()
            logger.info('Policy Browser Tab: AI Assist button clicked, toggled bottom pane.')

    def on_search(self):  # noqa: C901
        """Perform case-insensitive search with highlighting and rebuild tree."""
        query = self.search_var.get().strip().lower()
        if not query:
            self.refresh_tree()
            return
        # Gather data from repo
        compartments = self.policy_repo.compartments or []
        policies = self.policy_repo.policies or []

        # Helper: recursively filter hierarchy and collect node info for tree
        children_by_parent = {}
        for c in compartments:
            parent = c.get('parent_id', None)
            if parent not in children_by_parent:
                children_by_parent[parent] = []
            children_by_parent[parent].append(c)
        policies_by_compartment = {}
        for p in policies:
            comp_ocid = p.get('compartment_ocid', None)
            if comp_ocid not in policies_by_compartment:
                policies_by_compartment[comp_ocid] = []
            policies_by_compartment[comp_ocid].append(p)

        # -- Remove old statements_by_policy; search logic now uses correct filter by policy/compartment --

        def highlight(text):
            """Return text with query bolded (with ***), case-insensitive."""
            if not query or not text:
                return text
            low = text.lower()
            idx = low.find(query)
            if idx == -1:
                return text
            before = text[:idx]
            match = text[idx : idx + len(query)]
            after = text[idx + len(query) :]
            return before + '***' + match + '***' + after

        def matching_tags(tags):
            """Return matching tag display strings for the current query."""
            if not isinstance(tags, dict):
                return []
            matches = []
            for key, value in sorted(tags.items()):
                key_str = str(key)
                value_str = str(value)
                if query in key_str.lower() or query in value_str.lower():
                    matches.append(f'{highlight(key_str)}: {highlight(value_str)}')
            return matches

        def recurse_compartments(parent_ocid):
            nodes = []
            for c in children_by_parent.get(parent_ocid, []):
                comp_id_val = c.get('id')
                comp_name = c.get('name', '(Unnamed Compartment)')
                comp_desc = c.get('description') or '(No description)'
                comp_tag_matches = matching_tags(c.get('tags') or {})
                match_this = (query in comp_name.lower()) or (query in comp_desc.lower()) or bool(comp_tag_matches)
                # Policies for this compartment
                nodes_policies = []
                policies_here = policies_by_compartment.get(comp_id_val, [])
                for p in policies_here:
                    pol_name = p.get('policy_name', '(Unnamed Policy)')
                    policy_tag_matches = matching_tags(p.get('tags') or {})
                    # Match policy name against search
                    match_policy = query in pol_name.lower() or bool(policy_tag_matches)
                    highlight_policy_name = highlight(pol_name) if match_policy else pol_name

                    # Filter statements with the correct compartment/policy pair
                    filter_dict = {'policy_name': [pol_name]}
                    if comp_id_val:
                        filter_dict['compartment_ocid'] = [comp_id_val]
                    stmts = self.policy_repo.filter_policy_statements(filter_dict)
                    highlight_stmts = []
                    for s in stmts:
                        stmt_txt = s.get('statement_text', '(No statement text)')
                        if query in stmt_txt.lower():
                            highlight_stmts.append(('Statement: ' + highlight(stmt_txt), True))
                    if match_policy or highlight_stmts:
                        nodes_policies.append(
                            (
                                highlight_policy_name,  # Policy (possibly highlighted)
                                policy_tag_matches,  # Matching policy tags only
                                highlight_stmts,  # Only matching stmts
                            )
                        )
                # Descendant compartments
                descendant_nodes = recurse_compartments(comp_id_val)
                if match_this or nodes_policies or descendant_nodes:
                    out = {
                        'comp_name': (highlight(comp_name) if match_this else comp_name),
                        'statement_count_direct': c.get('statement_count_direct', 0),
                        'statement_count_cumulative': c.get('statement_count_cumulative', 0),
                        'comp_desc': highlight(comp_desc) if query in comp_desc.lower() else comp_desc,
                        'tag_matches': comp_tag_matches,
                        'policies': nodes_policies,  # [(policy_name, [tag_matches], [stmts])]
                        'descendants': descendant_nodes,
                        'should_expand': True,  # All matching paths expanded
                    }
                    nodes.append(out)
            return nodes

        # Build root
        all_ids = {c.get('id') for c in compartments if 'id' in c}
        root_parent_id_set = set()
        for c in compartments:
            parent = c.get('parent_id')
            if not parent or parent not in all_ids:
                root_parent_id_set.add(parent)
        roots = []
        for root_parent in root_parent_id_set:
            roots += recurse_compartments(root_parent)
        # Fallback if no roots
        if not roots:
            roots += recurse_compartments(None)
        # Populate treeview from nodes
        for i in self.tree.get_children():
            self.tree.delete(i)

        def tree_from_nodes(nodes, parent_id):  # noqa: C901
            for c in nodes:
                # Compartment node is always default background
                comp_node = self.tree.insert(parent_id, 'end', text=f'Compartment: {c["comp_name"]}', open=True)
                # Insert counts row only if limits option is set, with color/message logic
                if getattr(self, 'show_policy_data_var', None) is not None and self.show_policy_data_var.get():
                    cum_count = c.get('statement_count_cumulative', 0)
                    direct_count = c.get('statement_count_direct', 0)
                    chain_limit = self._chain_limit()
                    if not chain_limit:
                        count_tag = 'bg_yellow'
                        status_msg = ' (Limit not supplied)'
                    elif cum_count > chain_limit:
                        count_tag = 'bg_red'
                        status_msg = ' (Over limit! Reduce statements.)'
                    elif cum_count >= int(chain_limit * 0.85):
                        count_tag = 'bg_yellow'
                        status_msg = ' (Warning: 85%+ of maximum allowed)'
                    else:
                        count_tag = 'bg_green'
                        status_msg = ''
                    counts_display = f'Statement count - direct: {direct_count}, cumulative: {cum_count}{status_msg}'
                    self.tree.insert(comp_node, 'end', text=counts_display, open=False, tags=(count_tag,))
                self.tree.insert(comp_node, 'end', text=f'Description: {c["comp_desc"]}', open=False)
                comp_tag_matches = c.get('tag_matches', [])
                if comp_tag_matches:
                    tags_node = self.tree.insert(comp_node, 'end', text='Tags:', open=True)
                    for tag_text in comp_tag_matches:
                        self.tree.insert(tags_node, 'end', text=tag_text, open=False)
                policies = c.get('policies', [])
                if policies:
                    policies_parent = self.tree.insert(comp_node, 'end', text='Policies', open=True)
                    for pol_name, tag_matches, stmts in policies:
                        pol_node = self.tree.insert(policies_parent, 'end', text=f'Policy: {pol_name}', open=True)
                        if tag_matches:
                            tags_node = self.tree.insert(pol_node, 'end', text='Tags:', open=True)
                            for tag_text in tag_matches:
                                self.tree.insert(tags_node, 'end', text=tag_text, open=False)
                        for stmt_txt, _ in stmts:
                            self.tree.insert(pol_node, 'end', text=stmt_txt, open=False)
                tree_from_nodes(c.get('descendants', []), comp_node)

        tree_from_nodes(roots, '')

    def _chain_limit(self) -> int | None:
        """Return the active snapshot's hierarchy limit, if it is known."""
        value = (getattr(self.policy_repo, 'tenancy_policy_limits', {}) or {}).get(
            'policy_statements_per_compartment_chain_count'
        )
        try:
            return int(value) if int(value) > 0 else None
        except (TypeError, ValueError):
            return None

    def _policy_data_summary(self) -> str:
        limits = getattr(self.policy_repo, 'tenancy_policy_limits', {}) or {}
        policies_limit = limits.get('policies_count')
        chain_limit = self._chain_limit()
        if not policies_limit or not chain_limit:
            if self._is_offline_snapshot():
                return 'Limits not supplied: enter policies-count and chain count below.'
            return 'Live OCI limits unavailable. Verify limits access, then reload the tenancy data.'
        max_chain = max(
            (int(c.get('statement_count_cumulative', 0) or 0) for c in self.policy_repo.compartments or []),
            default=0,
        )
        return (
            f'Policy objects: {len(self.policy_repo.policies)} / {policies_limit} | '
            f'Chain statements: {max_chain} / {chain_limit} | Source: {limits.get("source", "unknown")}'
        )

    def _is_offline_snapshot(self) -> bool:
        """Manual limits are valid only for a named cache or CIS import."""
        return bool(
            getattr(self.policy_repo, 'current_cache_name', '')
            or getattr(self.policy_repo, 'loaded_from_compliance_output', False)
        )

    def _toggle_policy_data(self) -> None:
        if self.show_policy_data_var.get():
            offline_snapshot = self._is_offline_snapshot()
            if not offline_snapshot:
                # Never let an earlier cache/CIS override appear as a live
                # tenancy value, even if a live limits request later fails.
                self.policy_repo.tenancy_policy_limits = {}
            if not offline_snapshot and getattr(self.policy_repo, 'limits_client', None):
                self.policy_repo.fetch_tenancy_policy_statement_limits()
            limits = getattr(self.policy_repo, 'tenancy_policy_limits', {}) or {}
            self.user_policy_limit_var.set(str(limits.get('policies_count') or ''))
            self.user_chain_limit_var.set(str(limits.get('policy_statements_per_compartment_chain_count') or ''))
            self.policy_data_summary_var.set(self._policy_data_summary())
            self.policy_data_frame.pack(fill='x', padx=5, pady=(0, 3))
            if not offline_snapshot:
                self.policy_limit_input_frame.pack_forget()
            else:
                self.policy_limit_input_frame.pack(side='left')
        else:
            self.policy_data_frame.pack_forget()
        self.refresh_tree()

    def _apply_user_supplied_limits(self) -> None:
        try:
            self.policy_repo.set_user_supplied_tenancy_policy_limits(
                self.user_policy_limit_var.get(), self.user_chain_limit_var.get()
            )
        except ValueError as exc:
            tkmessagebox.showerror('Invalid limits', str(exc))
            return
        cache_name = getattr(self.policy_repo, 'current_cache_name', '')
        if cache_name:
            self.app.cache_service.cache.update_tenancy_policy_limits(
                cache_name, self.policy_repo.tenancy_policy_limits
            )
        self.policy_data_summary_var.set(self._policy_data_summary())
        recommendations_tab = getattr(self.app, 'policy_recommendations_tab', None)
        if recommendations_tab is not None:
            if hasattr(recommendations_tab, 'tenancy_limit_label_var'):
                recommendations_tab.tenancy_limit_label_var.set(recommendations_tab._tenancy_limits_summary())
            if hasattr(recommendations_tab, 'update_limits_tab_output'):
                recommendations_tab.update_limits_tab_output()
        self.refresh_tree()

    def on_clear_search(self):
        """Clear search box and show full unfiltered tree."""
        self.search_var.set('')
        self.refresh_tree()

    def post_load_update_ui(self):
        """Populate Policy Browser data widgets after repository data has been loaded."""
        self._data_initialized = True
        self._update_reload_policy_button_state()
        self.refresh_tree()

    def refresh_tree(self):
        """Refresh the compartment/policy/statement tree from latest repo data."""
        for i in self.tree.get_children():
            self.tree.delete(i)
        self._populate_tree()
        self._refresh_tag_catalog_display()

    def _collect_defined_tag_namespace_keys(self) -> dict[str, dict[str, Any]]:  # noqa: C901
        """Collect namespace catalog rows, including keys + compartment path."""
        repo_catalog = getattr(self.policy_repo, 'defined_tag_namespace_keys', None)
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
                        # Legacy path where keys is set/list
                        for key_name in raw_keys:
                            key_map[str(key_name)] = None
                    comp_ocid = entry.get('compartment_ocid')
                    comp_path = entry.get('compartment_path')
                else:
                    # Backward compatibility with legacy shape {namespace: set(keys)}
                    key_map = {str(k): None for k in (entry or [])}
                    comp_ocid = None
                    comp_path = None

                if not comp_path and hasattr(self.policy_repo, 'get_compartment_path_for_ocid'):
                    comp_path = self.policy_repo.get_compartment_path_for_ocid(comp_ocid)

                normalized[ns_str] = {
                    'keys': key_map,
                    'compartment_ocid': comp_ocid,
                    'compartment_path': comp_path or 'UNKNOWN_PATH',
                }

            total_keys = 0
            for row in normalized.values():
                row_keys = row.get('keys') or {}
                if isinstance(row_keys, dict):
                    total_keys += len(row_keys)

            logger.info(
                'Tag catalog source=repository in-memory catalog: %d namespace(s), %d key(s).',
                len(normalized),
                total_keys,
            )
            return normalized

        namespace_to_rows: dict[str, dict[str, Any]] = {}
        policies = self.policy_repo.policies or []
        logger.info(
            'Tag catalog source=fallback policy defined_tags scan across %d loaded policies.',
            len(policies),
        )
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
                        or self.policy_repo.get_compartment_path_for_ocid(policy.get('compartment_ocid')),
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
                    # Non-dict values are uncommon for OCI defined_tags, but keep visible
                    key_map['(value)'] = None

        total_keys = 0
        for row in namespace_to_rows.values():
            row_keys = row.get('keys') or {}
            if isinstance(row_keys, dict):
                total_keys += len(row_keys)

        logger.info(
            'Tag catalog fallback scan complete: %d namespace(s), %d key(s).',
            len(namespace_to_rows),
            total_keys,
        )
        return namespace_to_rows

    def _refresh_tag_catalog_display(self):  # noqa: C901
        """Refresh the small tag namespace/key catalog on the Policy Browser tab."""
        if not hasattr(self, 'tag_catalog_tree'):
            return

        logger.info('Refreshing Policy Browser tag namespace/key catalog display.')

        for item in self.tag_catalog_tree.get_children():
            self.tag_catalog_tree.delete(item)
        if hasattr(self, 'tag_catalog_values_tree'):
            for item in self.tag_catalog_values_tree.get_children():
                self.tag_catalog_values_tree.delete(item)
        self._tag_catalog_top_row_meta = {}

        namespace_catalog = self._collect_defined_tag_namespace_keys()
        if not namespace_catalog:
            self.tag_catalog_summary_var.set('No defined tags discovered in loaded policy data.')
            logger.info('Tag catalog display refresh complete: no namespace data available.')
            return

        namespace_count = len(namespace_catalog)
        key_count = 0
        for entry in namespace_catalog.values():
            entry_keys = entry.get('keys') or {}
            if isinstance(entry_keys, dict):
                key_count += len(entry_keys)
        self.tag_catalog_summary_var.set(f'Discovered {namespace_count} namespace(s), {key_count} key(s).')

        rendered_rows = 0
        for namespace in sorted(namespace_catalog.keys(), key=lambda x: x.lower()):
            entry = namespace_catalog[namespace]
            compartment_path = str(entry.get('compartment_path') or 'UNKNOWN_PATH')
            entry_keys = entry.get('keys') or {}
            if not isinstance(entry_keys, dict):
                entry_keys = {}

            sorted_key_names = sorted([str(k) for k in entry_keys.keys()], key=lambda x: x.lower())
            if not sorted_key_names:
                iid = self.tag_catalog_tree.insert(
                    '', 'end', values=(namespace, compartment_path, '(no keys discovered)')
                )
                self._tag_catalog_top_row_meta[iid] = {
                    'namespace': namespace,
                    'compartment_path': compartment_path,
                    'key_name': '(no keys discovered)',
                    'values': None,
                }
                rendered_rows += 1
                continue

            for key_name in sorted_key_names:
                values = entry_keys.get(key_name)
                normalized_values: list[str] | None = None
                if isinstance(values, list | tuple | set) and len(values) > 0:
                    normalized_values = sorted({str(v) for v in values}, key=lambda x: x.lower())
                iid = self.tag_catalog_tree.insert('', 'end', values=(namespace, compartment_path, key_name))
                self._tag_catalog_top_row_meta[iid] = {
                    'namespace': namespace,
                    'compartment_path': compartment_path,
                    'key_name': key_name,
                    'values': normalized_values,
                }
                rendered_rows += 1

        # Select first row by default so lower values table is populated.
        children = self.tag_catalog_tree.get_children()
        if children:
            first = children[0]
            self.tag_catalog_tree.selection_set(first)
            self._render_tag_value_detail_for_top_item(first)
        elif hasattr(self, 'tag_catalog_values_tree'):
            self.tag_catalog_values_tree.insert('', 'end', values=('No values to display.',))

        logger.info(
            'Tag catalog display refresh complete: rendered %d namespace/key row(s).',
            rendered_rows,
        )

    def _on_tag_catalog_selection_changed(self, _event=None):
        """Render lower value table from currently selected namespace/key row."""
        selection = self.tag_catalog_tree.selection()
        if not selection:
            return
        self._render_tag_value_detail_for_top_item(selection[0])

    def _render_tag_value_detail_for_top_item(self, item_id: str):
        """Populate lower values table for selected top-row item."""
        if not hasattr(self, 'tag_catalog_values_tree'):
            return
        for item in self.tag_catalog_values_tree.get_children():
            self.tag_catalog_values_tree.delete(item)

        meta = self._tag_catalog_top_row_meta.get(item_id, {})
        values = meta.get('values')
        key_name = str(meta.get('key_name') or '')

        if key_name == '(no keys discovered)':
            self.tag_catalog_values_tree.insert('', 'end', values=('User-Supplied',))
            return

        if isinstance(values, list) and values:
            for value in values:
                self.tag_catalog_values_tree.insert('', 'end', values=(value,))
            return

        self.tag_catalog_values_tree.insert('', 'end', values=('User-Supplied',))

    def _populate_tree(self):  # noqa: C901
        # Get all compartments and policies from the repo
        # compartments = self.policy_repo.compartments if hasattr(self.policy_repo, "compartments") else []
        # policies = self.policy_repo.policies if hasattr(self.policy_repo, "policies") else []
        # statements = self.policy_repo.regular_statements if hasattr(self.policy_repo, "regular_statements") else []

        compartments = self.policy_repo.compartments or []
        policies = self.policy_repo.policies or []
        # Combine regular, alias (define), and cross-tenancy statements for the policy browser tree
        statements = (
            (self.policy_repo.regular_statements or [])
            + (self.policy_repo.defined_aliases or [])
            + (self.policy_repo.cross_tenancy_statements or [])
        )
        logger.info(
            f'Populating tree: {len(compartments)} compartments, {len(policies)} policies, {len(statements)} statements (incl. aliases and cross-tenancy)'
        )
        if not compartments:
            logger.info('No compartments found.')
        if not policies:
            logger.info('No policies found.')
        if not statements:
            logger.info('No policy statements found.')

        # Parent mapping for hierarchy walk
        children_by_parent = {}
        for c in compartments:
            parent = c.get('parent_id', None)
            if parent not in children_by_parent:
                children_by_parent[parent] = []
            children_by_parent[parent].append(c)

        logger.info(
            f'children_by_parent keys (potential roots): {list(children_by_parent.keys())[:10]}... (showing up to 10)'
        )

        # Build policy mapping: compartment OCID → [policies]
        policies_by_compartment = {}
        for p in policies:
            comp_ocid = p.get('compartment_ocid', None)
            if comp_ocid not in policies_by_compartment:
                policies_by_compartment[comp_ocid] = []
            policies_by_compartment[comp_ocid].append(p)

        logger.info(
            f'policies_by_compartment keys (comp_ocids): {list(policies_by_compartment.keys())[:10]}... (showing up to 10)'
        )

        # -- REMOVE old statements_by_policy mapping --
        # Instead, will fetch statements per-policy per-compartment below

        logger.info('Ready to build policy browser tree using filtered statements per policy/compartment.')

        # Treeview: recursively insert compartments, their policies, then statements

        def insert_compartment_tree(parent_id, parent_ocid):  # noqa: C901
            children = children_by_parent.get(parent_ocid, [])
            logger.debug(f'Inserting {len(children)} compartments with parent_id={parent_ocid}')
            for c in children:
                comp_id_val = c.get('id')
                if not comp_id_val:
                    logger.info(f'Skipping compartment with missing id: {c!r}')
                    continue  # skip compartments missing a valid id
                comp_name = c.get('name', '(Unnamed Compartment)')
                # Pull in direct/cumulative statement counts
                direct_count = c.get('statement_count_direct', 0)
                cumulative_count = c.get('statement_count_cumulative', 0)
                comp_display = f'Compartment: {comp_name}'

                # Compartment row - always default (no color)
                comp_node = self.tree.insert(parent_id, 'end', text=comp_display, open=True)
                logger.debug(f'Inserted compartment: {comp_display} (id={comp_id_val}) parent_id={parent_ocid}')

                # Show or hide counts row based on user option, and only color this row if visible
                if getattr(self, 'show_policy_data_var', None) is not None and self.show_policy_data_var.get():
                    chain_limit = self._chain_limit()
                    if not chain_limit:
                        count_tag = 'bg_yellow'
                        status_msg = ' (Limit not supplied)'
                    elif cumulative_count > chain_limit:
                        count_tag = 'bg_red'
                        status_msg = ' (Over limit! Reduce statements.)'
                    elif cumulative_count >= int(chain_limit * 0.85):
                        count_tag = 'bg_yellow'
                        status_msg = ' (Warning: 85%+ of maximum allowed)'
                    else:
                        count_tag = 'bg_green'
                        status_msg = ''
                    counts_display = (
                        f'Statement count - direct: {direct_count}, cumulative: {cumulative_count}{status_msg}'
                    )
                    self.tree.insert(comp_node, 'end', text=counts_display, open=False, tags=(count_tag,))

                # Add compartment description node
                comp_desc = c.get('description') or '(No description)'
                self.tree.insert(comp_node, 'end', text=f'Description: {comp_desc}', open=False)

                # Add compartment tags if present
                comp_tags = c.get('tags') or {}
                if comp_tags:
                    tags_node = self.tree.insert(comp_node, 'end', text='Tags:', open=False)
                    for tag_k, tag_v in sorted(comp_tags.items()):
                        self.tree.insert(tags_node, 'end', text=f'{tag_k}: {tag_v}', open=False)

                # Add all policies under this compartment, grouped under "Policies" node
                policies_here = policies_by_compartment.get(comp_id_val, [])
                # Only add "Policies" node if there are policies here
                if len(policies_here) > 0:
                    policies_parent = self.tree.insert(comp_node, 'end', text='Policies', open=False)
                    logger.debug(
                        f'Inserting {len(policies_here)} policies under compartment {comp_name} (id={comp_id_val})'
                    )
                    for p in policies_here:
                        pol_name = p.get('policy_name', '(Unnamed Policy)')
                        policy_ocid = p.get('policy_ocid', 'unknown_ocid')
                        compartment_ocid = p.get('compartment_ocid', None)
                        pol_node = self.tree.insert(policies_parent, 'end', text=f'Policy: {pol_name}', open=False)
                        logger.debug(f'Inserted policy: {pol_name} (ocid={policy_ocid}) under compartment {comp_name}')

                        # If policy contains tags, show them as expandable child node
                        tags = p.get('tags') or {}
                        if tags:
                            tags_node = self.tree.insert(pol_node, 'end', text='Tags:', open=False)
                            for k, v in sorted(tags.items()):
                                self.tree.insert(tags_node, 'end', text=f'{k}: {v}', open=False)

                        # Fetch and display only the correct statements for this policy/compartment pair
                        filter_dict = {'policy_name': [pol_name]}
                        if compartment_ocid:
                            filter_dict['compartment_ocid'] = [compartment_ocid]
                        stmts = self.policy_repo.filter_policy_statements(filter_dict)
                        logger.debug(
                            f'Inserting {len(stmts)} statements under policy {pol_name} in compartment {compartment_ocid}'
                        )
                        for s in stmts:
                            stmt_txt = s.get('statement_text', '(No statement text)')
                            self.tree.insert(pol_node, 'end', text=f'Statement: {stmt_txt}', open=False)
                            logger.debug(
                                f'Inserted statement under policy {pol_name} in {compartment_ocid}: {stmt_txt!r}'
                            )

                insert_compartment_tree(comp_node, comp_id_val)

        # Compute set of all compartment IDs
        all_ids = {c.get('id') for c in compartments if 'id' in c}
        # Find all roots: compartments whose parent_id is missing from all_ids (tenancy root or orphan)
        root_parent_id_set = set()
        for c in compartments:
            parent = c.get('parent_id')
            if not parent or parent not in all_ids:
                root_parent_id_set.add(parent)
        logger.info(f'Found {len(root_parent_id_set)} root(s): {root_parent_id_set}')
        roots_inserted = False
        for root_parent in root_parent_id_set:
            roots_inserted = True
            logger.info(f'Inserting hierarchy for root parent_id={root_parent}')
            insert_compartment_tree('', root_parent)
        # Fallback: try legacy parent_id=None if no roots were found
        if not roots_inserted:
            logger.info('No root_parent_id detected; using parent_id=None as tree root')
            insert_compartment_tree('', None)

    def _on_right_click(self, event):
        # Identify item
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return
        node_text = self.tree.item(item_id, 'text')
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label='Focus in Next Tab', command=lambda: self._focus_in_next_tab(item_id, node_text))
        menu.tk_popup(event.x_root, event.y_root)

    def _on_tag_catalog_right_click(self, event):
        """Context menu for tag catalog table rows."""
        item_id = self.tag_catalog_tree.identify_row(event.y)
        using_value_table = False
        if not item_id and hasattr(self, 'tag_catalog_values_tree'):
            item_id = self.tag_catalog_values_tree.identify_row(event.y)
            using_value_table = bool(item_id)

        if not item_id:
            return

        if using_value_table:
            # Keep top selection as source-of-truth for namespace/key metadata.
            value_selection = self.tag_catalog_values_tree.selection()
            if not value_selection:
                self.tag_catalog_values_tree.selection_set(item_id)
            top_selection = self.tag_catalog_tree.selection()
            if not top_selection:
                return
            top_item_id = top_selection[0]
        else:
            self.tag_catalog_tree.selection_set(item_id)
            top_item_id = item_id

        meta = self._tag_catalog_top_row_meta.get(top_item_id)
        if not meta:
            return

        selected_tag_value = self._get_selected_tag_value()

        menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label='Open in Tag-based Access Tab',
            command=lambda row_meta=meta, tag_value=selected_tag_value: self._open_tag_row_in_tag_based_access_tab(
                row_meta=row_meta,
                tag_value=tag_value,
            ),
        )
        menu.tk_popup(event.x_root, event.y_root)

    def _get_selected_tag_value(self) -> str:
        """Return selected value from the lower values table, if any."""
        if not hasattr(self, 'tag_catalog_values_tree'):
            return ''
        selection = self.tag_catalog_values_tree.selection()
        if not selection:
            return ''
        value_row = self.tag_catalog_values_tree.item(selection[0], 'values')
        if not value_row:
            return ''
        value_text = str(value_row[0]).strip() if len(value_row) > 0 else ''
        if value_text in ('User-Supplied', 'No values to display.'):
            return ''
        return value_text

    def _open_tag_row_in_tag_based_access_tab(self, row_meta: dict[str, Any], tag_value: str = ''):  # noqa: C901
        """Navigate to Tag-based Access tab and pre-fill filters from selected catalog row."""
        tag_tab = getattr(self.app, 'tag_based_access_tab', None)
        notebook = getattr(self.app, 'notebook', None)
        if not tag_tab or not notebook:
            logger.info('Tag-based Access tab is not available for navigation.')
            return

        try:
            tab_ids = notebook.tabs()
            if str(tag_tab) not in tab_ids:
                import tkinter.messagebox as tkmessagebox

                tkmessagebox.showinfo(
                    'Advanced Tabs Hidden',
                    'Tag-based Access is currently hidden. Please enable Advanced Tabs from Settings first.',
                )
                return
        except Exception:
            pass

        namespace = str(row_meta.get('namespace') or '').strip()
        key_name = str(row_meta.get('key_name') or '').strip()
        if key_name == '(no keys discovered)':
            key_name = ''

        try:
            if hasattr(tag_tab, 'tag_namespace_var'):
                tag_tab.tag_namespace_var.set(namespace)
            if hasattr(tag_tab, 'tag_key_var'):
                tag_tab.tag_key_var.set(key_name)
            if hasattr(tag_tab, 'tag_value_var'):
                tag_tab.tag_value_var.set(tag_value or '')
            if hasattr(tag_tab, 'access_type_var'):
                tag_tab.access_type_var.set('Any')

            # Ensure latest data is available before applying filters.
            if hasattr(tag_tab, 'populate_data'):
                tag_tab.populate_data()
            if hasattr(tag_tab, '_apply_filters_and_refresh'):
                tag_tab._apply_filters_and_refresh()

            notebook.select(tag_tab)
            logger.info(
                'Policy Browser tag-catalog navigation: namespace=%s key=%s value=%s -> Tag-based Access tab',
                namespace,
                key_name,
                tag_value,
            )
        except Exception:
            logger.info('Failed to navigate to Tag-based Access tab from tag catalog row.', exc_info=True)

    def expand_collapse_all(self, expand: bool = True):
        """Expand or collapse all nodes in the tree."""
        for item in self.tree.get_children():
            self._expand_collapse_recursive(item, expand)

    def expand_collapse_compartments(self, only=True, expand=True):
        """Expand/collapse all compartments, but collapse their Policies nodes and below."""

        def action(node, lvl):
            txt = self.tree.item(node, 'text')
            # Level 0 is root compartments; 1 is compartment; 2 is Policies node, etc.
            if lvl == 0 or txt.startswith('Compartment:') or txt.startswith('ROOT'):
                self.tree.item(node, open=expand)
                for child in self.tree.get_children(node):
                    # Policies node
                    child_txt = self.tree.item(child, 'text')
                    # For expand, collapse policies (so you can see just compartment outline)
                    if child_txt == 'Policies':
                        self.tree.item(child, open=not expand)
                        # Also collapse policy nodes under Policies node
                        for pchild in self.tree.get_children(child):
                            self.tree.item(pchild, open=False)
                    else:
                        self.tree.item(child, open=False)
            else:
                self.tree.item(node, open=False)

        for item in self.tree.get_children():
            action(item, 0)
            for child in self.tree.get_children(item):
                action(child, 1)
                for grandchild in self.tree.get_children(child):
                    action(grandchild, 2)

    def _expand_collapse_recursive(self, node, expand: bool):
        self.tree.item(node, open=expand)
        for child in self.tree.get_children(node):
            self._expand_collapse_recursive(child, expand)

    def _on_tree_select(self, event):
        # When a Statement node is selected, populate statement for AI context
        selected_id = self.tree.focus()
        if not selected_id:
            return
        node_text = self.tree.item(selected_id, 'text')
        if node_text.startswith('Statement: '):
            statement = node_text.replace('Statement:', '', 1).strip()
            # Populate for AI
            if hasattr(self.app, 'policy_query_var'):
                self.app.policy_query_label_text.set('Policy Statement\nInsights:')
                self.app.policy_query_var.set(statement)
            if hasattr(self.app, 'ai_additional_instructions'):
                self.app.ai_additional_instructions = (
                    'Analyze the selected OCI policy statement. Show how the statement breaks down '
                    'into its components such as action, subject, verb, resource, conditions, and effective path. '
                    'Explain its implications on permissions within the OCI environment.'
                )
            logger.info(f'Selected statement for AI: {statement}')

    def _focus_in_next_tab(self, item_id, node_text):
        # This function determines what the user clicked on and applies filter logic to the Policies Tab.
        poltab = getattr(self.app, 'policies_tab', None)
        if not poltab:
            logger.info('No policies_tab found, cannot focus.')
            return
        logger.info(f'Policy Browser - Focus in Next Tab action: {node_text!r}')
        node_text = node_text.strip()
        # Clear all filters first
        poltab.subject_filter_var.set('')
        poltab.verb_filter_var.set('')
        poltab.action_filter_var.set('Both')
        poltab.location_filter_var.set('')
        poltab.resource_filter_var.set('')
        poltab.hierarchy_filter_var.set('')
        poltab.condition_filter_var.set('')
        poltab.text_filter_var.set('')
        poltab.effective_path_var.set('')
        poltab.policy_filter_var.set('')

        if node_text.startswith('Compartment:'):
            # Example: "Compartment: ROOT" or similar
            compartment_name = node_text.replace('Compartment:', '').strip()
            poltab.location_filter_var.set(compartment_name)
        elif node_text.startswith('Policy:'):
            # Example: "Policy: MyPolicyName"
            policy_name = node_text.replace('Policy:', '').strip()
            poltab.policy_filter_var.set(policy_name)
        elif node_text.startswith('Statement:'):
            # Statement line: just apply an exact match to statement text
            # Could use a more unique key if available
            statement_brief = node_text.replace('Statement:', '').strip()
            poltab.text_filter_var.set(statement_brief)
        else:
            # fallback: just show filter applied with text info
            pass
        # Always show all subject types when focusing from browser
        poltab.chk_show_service.set(True)
        poltab.chk_show_dynamic.set(True)
        poltab.chk_show_resource.set(True)
        poltab.chk_show_regular.set(True)
        # Switch to Policies Tab and update output
        if hasattr(self.app, 'notebook'):
            idx = None
            try:
                idx = self.app.notebook.tabs().index(str(poltab))
            except Exception:
                pass
            if idx is not None:
                self.app.notebook.select(poltab)
            else:
                # fallback: select by tab ref
                self.app.notebook.select(self.app.policies_tab)
        poltab.update_policy_output()
