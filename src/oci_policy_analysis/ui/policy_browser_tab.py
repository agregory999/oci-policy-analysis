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
from tkinter import ttk

from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.ui.base_tab import BaseUITab

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
                'Browse all compartments, policies, and policy statements. '
                'Tree expands to reveal policies in each compartment and all their statement text. '
                'Right-click a policy or statement for navigation or actions.'
            ),
        )
        self.app = app
        self.settings = settings
        self.policy_repo = app.policy_compartment_analysis
        self._build_ui()

    def _build_ui(self):
        logger.info('Building UI for Policy Browser Tab')
        # Parent is a ttk.Notebook tab (self). Force this Frame to expand!
        self.pack(fill='both', expand=True)
        logger.info(
            f'self.winfo_class={self.winfo_class()} is mapped: {self.winfo_ismapped()}, size: {self.winfo_width()}x{self.winfo_height()}'
        )

        # Search, Expand/Collapse Button Row
        button_row = ttk.Frame(self)
        button_row.pack(fill='x', expand=False, padx=10, pady=(8, 2))

        # --- Button/Entry/Labelling UI (reordered per feedback) ---
        expand_all_btn = ttk.Button(
            button_row, text='Expand All', command=lambda: self.expand_collapse_all(expand=True)
        )
        expand_all_btn.pack(side='left', padx=(0, 3))
        self.add_context_help(expand_all_btn, 'Expand all nodes in the tree.')

        collapse_all_btn = ttk.Button(
            button_row, text='Collapse All', command=lambda: self.expand_collapse_all(expand=False)
        )
        collapse_all_btn.pack(side='left', padx=(0, 3))
        self.add_context_help(collapse_all_btn, 'Collapse all nodes in the tree.')

        expand_comp_btn = ttk.Button(
            button_row,
            text='Expand Compartments Only',
            command=lambda: self.expand_collapse_compartments(only=True, expand=True),
        )
        expand_comp_btn.pack(side='left', padx=(8, 3))
        self.add_context_help(expand_comp_btn, 'Expand compartments only, collapse all policies/statements under them.')

        # Vertical separator for clarity
        sep = ttk.Separator(button_row, orient='vertical')
        sep.pack(side='left', fill='y', padx=(8, 8), pady=3)

        # Label for text search, then live search box, then clear button
        search_label = ttk.Label(button_row, text='Search:')
        search_label.pack(side='left', padx=(0, 2), pady=2)

        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(button_row, textvariable=self.search_var, width=32)
        search_entry.pack(side='left', padx=(0, 4), pady=2)

        clear_btn = ttk.Button(button_row, text='Clear', command=self.on_clear_search)
        clear_btn.pack(side='left', padx=(0, 3), pady=2)

        self.add_context_help(
            search_entry,
            'Type to search compartments, policies, or statements (case-insensitive). Filtering occurs as you type.',
        )
        self.add_context_help(
            search_label,
            'Live text search for nodes. All containing/hierarchical nodes will be shown, results highlighted.',
        )
        self.add_context_help(
            clear_btn,
            'Reset the search and show all compartments, policies, and statements.',
        )

        # Live search via Var trace
        self.search_var.trace_add('write', lambda *args: self.on_search())

        logger.info('Expand/collapse/search/clear buttons and entry added to Policy Browser tab UI.')

        label_frm_tree = ttk.LabelFrame(self, text='Compartment / Policy / Statement Tree', borderwidth=5)
        label_frm_tree.pack(fill='both', expand=True, padx=10, pady=10)
        logger.debug(
            f'label_frm_tree.winfo_class={label_frm_tree.winfo_class()} is mapped: {label_frm_tree.winfo_ismapped()}, size: {label_frm_tree.winfo_width()}x{label_frm_tree.winfo_height()}'
        )

        # Tree widget for the browser — give it a visible border (relief)
        self.tree = ttk.Treeview(label_frm_tree, show='tree')
        self.tree.pack(fill='both', expand=True, side='top', padx=2, pady=2)
        self.tree.configure(style='Treeview')
        logger.info(
            f'Treeview created: is mapped: {self.tree.winfo_ismapped()}, size: {self.tree.winfo_width()}x{self.tree.winfo_height()}'
        )

        self.tree.heading('#0', text='OCI Compartments → Policies → Statements', anchor='w')
        self.add_context_help(
            self.tree,
            'This tree shows the full compartment hierarchy with all OCI policies underneath. Expand compartments to view their policies and each statement. Right-click for actions.',
        )
        self._populate_tree()
        logger.info('Finished _build_ui; tree and parent should be visible and expanded')
        # Bind right-click menu
        self.tree.bind('<Button-3>', self._on_right_click)

    def on_search(self):  # noqa: C901
        """Perform case-insensitive search with highlighting and rebuild tree."""
        query = self.search_var.get().strip().lower()
        if not query:
            self.refresh_tree()
            return
        # Gather data from repo
        compartments = self.policy_repo.compartments or []
        policies = self.policy_repo.policies or []
        statements = (
            (self.policy_repo.regular_statements or [])
            + (self.policy_repo.defined_aliases or [])
            + (self.policy_repo.cross_tenancy_statements or [])
        )
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
        statements_by_policy = {}
        for s in statements:
            policy_name = s.get('policy_name')
            if not policy_name:
                continue
            if policy_name not in statements_by_policy:
                statements_by_policy[policy_name] = []
            statements_by_policy[policy_name].append(s)

        # Recursive filter
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
            # Simple: wrap with ***
            return before + '***' + match + '***' + after

        def search_statements(policy_name):
            """Return list of stmts with highlight if matching, else empty if none match query."""
            stmts = statements_by_policy.get(policy_name, [])
            # Each: ("Statement: ...", highlight) or None
            results = []
            for s in stmts:
                stmt_txt = s.get('statement_text', '(No statement text)')
                if query in stmt_txt.lower():
                    results.append(('Statement: ' + highlight(stmt_txt), True))
                else:
                    # Still show if parent path matches, but not highlighted
                    results.append(('Statement: ' + stmt_txt, False))
            return [r for r in results if r[1]]

        def recurse_compartments(parent_ocid):
            nodes = []
            for c in children_by_parent.get(parent_ocid, []):
                comp_id_val = c.get('id')
                comp_name = c.get('name', '(Unnamed Compartment)')
                comp_desc = c.get('description') or '(No description)'
                match_this = (query in comp_name.lower()) or (query in comp_desc.lower())
                # Policies for this compartment
                nodes_policies = []
                policies_here = policies_by_compartment.get(comp_id_val, [])
                for p in policies_here:
                    pol_name = p.get('policy_name', '(Unnamed Policy)')
                    # policy_ocid = p.get('policy_ocid', 'unknown_ocid')
                    match_policy = query in pol_name.lower()
                    highlight_policy_name = highlight(pol_name) if match_policy else pol_name
                    # Filter statements
                    highlight_stmts = []
                    for s in statements_by_policy.get(pol_name, []):
                        stmt_txt = s.get('statement_text', '(No statement text)')
                        match_stmt = query in stmt_txt.lower()
                        if match_stmt:
                            highlight_stmts.append(('Statement: ' + highlight(stmt_txt), True))
                    if match_policy or highlight_stmts:
                        nodes_policies.append(
                            (
                                highlight_policy_name,  # Policy (possibly highlighted)
                                highlight_stmts,  # Always only matching stmts
                            )
                        )
                # Descendant compartments
                descendant_nodes = recurse_compartments(comp_id_val)
                # If anything below (or this) matches, include
                if match_this or nodes_policies or descendant_nodes:
                    out = {
                        'comp_name': highlight(comp_name) if match_this else comp_name,
                        'comp_desc': highlight(comp_desc) if query in comp_desc.lower() else comp_desc,
                        'policies': nodes_policies,  # [(policy_name, [stmts])]
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

        def tree_from_nodes(nodes, parent_id):
            for c in nodes:
                comp_node = self.tree.insert(parent_id, 'end', text=f'Compartment: {c["comp_name"]}', open=True)
                self.tree.insert(comp_node, 'end', text=f'Description: {c["comp_desc"]}', open=False)
                policies = c.get('policies', [])
                if policies:
                    policies_parent = self.tree.insert(comp_node, 'end', text='Policies', open=True)
                    for pol_name, stmts in policies:
                        pol_node = self.tree.insert(policies_parent, 'end', text=f'Policy: {pol_name}', open=True)
                        for stmt_txt, _ in stmts:
                            self.tree.insert(pol_node, 'end', text=stmt_txt, open=False)
                tree_from_nodes(c.get('descendants', []), comp_node)

        tree_from_nodes(roots, '')

    def on_clear_search(self):
        """Clear search box and show full unfiltered tree."""
        self.search_var.set('')
        self.refresh_tree()

    def refresh_tree(self):
        """Refresh the compartment/policy/statement tree from latest repo data."""
        for i in self.tree.get_children():
            self.tree.delete(i)
        self._populate_tree()

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

        # Build statement mapping: policy name → [statements]
        statements_by_policy = {}
        for s in statements:
            policy_name = s.get('policy_name')
            if not policy_name:
                continue
            if policy_name not in statements_by_policy:
                statements_by_policy[policy_name] = []
            statements_by_policy[policy_name].append(s)

        logger.info(
            f'statements_by_policy keys (policy names): {list(statements_by_policy.keys())[:10]}... (showing up to 10)'
        )

        # Treeview: recursively insert compartments, their policies, then statements

        def insert_compartment_tree(parent_id, parent_ocid):
            children = children_by_parent.get(parent_ocid, [])
            logger.info(f'Inserting {len(children)} compartments with parent_id={parent_ocid}')
            for c in children:
                comp_id_val = c.get('id')
                if not comp_id_val:
                    logger.info(f'Skipping compartment with missing id: {c!r}')
                    continue  # skip compartments missing a valid id
                comp_name = c.get('name', '(Unnamed Compartment)')
                comp_node = self.tree.insert(parent_id, 'end', text=f'Compartment: {comp_name}', open=True)
                logger.info(f'Inserted compartment: {comp_name} (id={comp_id_val}) parent_id={parent_ocid}')

                # Add compartment description node
                comp_desc = c.get('description') or '(No description)'
                self.tree.insert(comp_node, 'end', text=f'Description: {comp_desc}', open=False)

                # Add all policies under this compartment, grouped under "Policies" node
                policies_here = policies_by_compartment.get(comp_id_val, [])
                # Only add "Policies" node if there are policies here
                if len(policies_here) > 0:
                    policies_parent = self.tree.insert(comp_node, 'end', text='Policies', open=False)
                    logger.info(
                        f'Inserting {len(policies_here)} policies under compartment {comp_name} (id={comp_id_val})'
                    )
                    for p in policies_here:
                        pol_name = p.get('policy_name', '(Unnamed Policy)')
                        policy_ocid = p.get('policy_ocid', 'unknown_ocid')
                        pol_node = self.tree.insert(policies_parent, 'end', text=f'Policy: {pol_name}', open=False)
                        logger.info(f'Inserted policy: {pol_name} (ocid={policy_ocid}) under compartment {comp_name}')

                        # Statements for this policy
                        stmts = statements_by_policy.get(pol_name, [])
                        logger.info(f'Inserting {len(stmts)} statements under policy {pol_name}')
                        for s in stmts:
                            stmt_txt = s.get('statement_text', '(No statement text)')
                            # statement_brief = (stmt_txt[:120] + '...') if len(stmt_txt) > 120 else stmt_txt
                            self.tree.insert(pol_node, 'end', text=f'Statement: {stmt_txt}', open=False)
                            logger.debug(f'Inserted statement under policy {pol_name}: {stmt_txt!r}')

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
            status = f'Filtered for Compartment/Location: {compartment_name}'
        elif node_text.startswith('Policy:'):
            # Example: "Policy: MyPolicyName"
            policy_name = node_text.replace('Policy:', '').strip()
            poltab.policy_filter_var.set(policy_name)
            status = f'Filtered for Policy: {policy_name}'
        elif node_text.startswith('Statement:'):
            # Statement line: just apply an exact match to statement text
            # Could use a more unique key if available
            statement_brief = node_text.replace('Statement:', '').strip()
            poltab.text_filter_var.set(statement_brief)
            status = f'Filtered for Statement text: {statement_brief}'
        else:
            # fallback: just show filter applied with text info
            status = f'Focus action requested for: {node_text}'
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
        if hasattr(self.app, 'status_var'):
            self.app.status_var.set(status)
        logger.info(f'Policy Browser navigation: {status}')
        print(status)
