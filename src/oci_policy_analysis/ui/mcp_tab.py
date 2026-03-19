##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# mcp_tab.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

import json
import logging
import tkinter as tk
from importlib import resources
from logging import Filter
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import oci_policy_analysis.mcp_server as mcp_server
from oci_policy_analysis.common.logger import get_logger, set_component_level
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository
from oci_policy_analysis.logic.simulation_engine import PolicySimulationEngine
from oci_policy_analysis.mcp_server import (
    mcp_server_status,
    start_mcp_server_in_thread,
)
from oci_policy_analysis.ui.base_tab import BaseUITab


# Filter
class MCPFilter(Filter):
    def filter(self, record):
        return (
            record.name.startswith('oci-policy-analysis.mcp') or record.name.startswith('mcp.server')
            # or record.name.startswith('uvicorn')
        )


# Dedicated UI handler
class MCPTextHandler(logging.Handler):
    """Thread-safe handler for MCP tab."""

    def __init__(self, text_widget: ScrolledText):
        super().__init__(level=logging.NOTSET)
        self.text_widget = text_widget
        self.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] [%(name)s] %(message)s'))

    def emit(self, record):
        try:
            msg = self.format(record)
            self.text_widget.after(0, self._append, msg)
        except Exception:
            self.handleError(record)

    def _append(self, msg: str):
        self.text_widget.insert(tk.END, msg + '\n')
        self.text_widget.see(tk.END)


logger = get_logger('mcp_tab')


class McpTab(BaseUITab):
    """
    MCP Tab for OCI Policy Analysis UI.
    Allows starting/stopping the MCP server and viewing its logs.
    Methods:
        __init__: Initializes the McpTab with UI components and callbacks.
        _start_mcp: (Internal) Starts the MCP server in a separate thread.
    """

    def __init__(self, parent, app, policy_repo: PolicyAnalysisRepository, settings):
        super().__init__(
            parent,
            default_help_text=(
                'Start, stop, and view logs for the embedded MCP server (Model Context Protocol). '
                'The embedded MCP server exposes policy analysis capabilities via tools and APIs for integration and automation.'
            ),
            page_help_link='/usage.html#embedded-mcp-tab',
        )
        self.app = app
        self.settings = settings
        self.policy_repo = policy_repo
        self.server_running = False

        self._build_ui()
        self._attach_mcp_log_handler()
        self._start_status_poll()
        # Load static MCP tools metadata from packaged JSON (if available)
        self._load_static_tools_from_resource()

    def _build_ui(self):
        """Construct the MCP tab layout.

        Layout:
            - Top row: control panel on the left (start button, status, debug toggle),
              and a tools table on the right listing available MCP tools.
            - Bottom: existing MCP server log in a scrolled text area.
        """

        # --- Top section: controls + tools table in a horizontal split ---
        top_frame = ttk.Frame(self)
        top_frame.pack(fill=tk.BOTH, expand=False, padx=10, pady=(10, 0))

        # Control panel on the left
        ctrl_frame = ttk.LabelFrame(top_frame, text='Embedded MCP Control')
        ctrl_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 8))

        self.start_btn = ttk.Button(ctrl_frame, text='Start MCP Server', command=self._start_mcp)
        self.start_btn.grid(row=0, column=0, padx=5, pady=5, sticky='w')

        ttk.Label(ctrl_frame, text='Status:').grid(row=1, column=0, padx=5, pady=(2, 2), sticky='w')
        self.status_lbl = ttk.Label(ctrl_frame, text='Stopped', foreground='red')
        self.status_lbl.grid(row=1, column=1, padx=(0, 5), pady=(2, 2), sticky='w')

        self.debug_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            ctrl_frame,
            text='Enable MCP Debug Logging',
            variable=self.debug_var,
            command=self._toggle_debug,
        ).grid(row=2, column=0, columnspan=2, padx=5, pady=(4, 4), sticky='w')

        # Tools table on the right
        tools_frame = ttk.LabelFrame(top_frame, text='Available MCP Tools')
        tools_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        columns = ('name', 'description', 'inputs', 'outputs')
        self.tools_table = ttk.Treeview(tools_frame, columns=columns, show='headings', height=10)
        self.tools_table.heading('name', text='Tool Name')
        self.tools_table.heading('description', text='Description')
        self.tools_table.heading('inputs', text='Inputs')
        self.tools_table.heading('outputs', text='Outputs')

        self.tools_table.column('name', width=180, anchor='w')
        self.tools_table.column('description', width=260, anchor='w')
        self.tools_table.column('inputs', width=200, anchor='w')
        self.tools_table.column('outputs', width=200, anchor='w')

        tools_scroll_y = ttk.Scrollbar(tools_frame, orient='vertical', command=self.tools_table.yview)
        tools_scroll_x = ttk.Scrollbar(tools_frame, orient='horizontal', command=self.tools_table.xview)
        self.tools_table.configure(yscrollcommand=tools_scroll_y.set, xscrollcommand=tools_scroll_x.set)

        self.tools_table.grid(row=0, column=0, sticky='nsew')
        tools_scroll_y.grid(row=0, column=1, sticky='ns')
        tools_scroll_x.grid(row=1, column=0, sticky='ew')

        tools_frame.rowconfigure(0, weight=1)
        tools_frame.columnconfigure(0, weight=1)

        # Initially empty; tools will be populated from static metadata and/or after MCP server starts.
        self._populate_tools_table([])

        # Right-click context menu to open MCP docs for a selected tool
        self._tool_menu = tk.Menu(self, tearoff=0)
        self._tool_menu.add_command(label='Open Tool Docs…', command=self._open_selected_tool_docs)

        def _on_tools_right_click(event):
            row_id = self.tools_table.identify_row(event.y)
            if not row_id:
                return
            # Select the row under cursor so the handler knows which tool is active
            self.tools_table.selection_set(row_id)
            try:
                self._tool_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self._tool_menu.grab_release()

        self.tools_table.bind('<Button-3>', _on_tools_right_click)

        # --- Bottom: MCP server log ---
        ttk.Label(self, text='MCP Server Log:').pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.mcp_log = ScrolledText(self, height=14, width=100, wrap='word', font=('Consolas', 10))
        self.mcp_log.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.mcp_log.insert(tk.END, 'MCP log output will appear here...\n')

    def _populate_tools_table(self, tools: list[dict] | None) -> None:
        """Populate the tools table from a provided list of tool metadata.

        Each entry in ``tools`` is expected to be a dict with keys:
        name, description, inputs, outputs.
        """

        # Clear any existing rows
        for item in self.tools_table.get_children():
            self.tools_table.delete(item)

        tools = tools or []
        for tool in tools:
            name = str(tool.get('name', ''))
            desc = str(tool.get('description', ''))
            inputs = str(tool.get('inputs', ''))
            outputs = str(tool.get('outputs', ''))
            self.tools_table.insert('', tk.END, values=(name, desc, inputs, outputs))

    def _open_selected_tool_docs(self) -> None:
        """Open the MCP documentation section for the selected tool.

        Currently this links to the general MCP docs page; if per-tool
        anchors are added later, we can append a fragment using the tool name.
        """

        selection = self.tools_table.selection()
        if not selection:
            return
        item_id = selection[0]
        values = self.tools_table.item(item_id, 'values') or ()
        tool_name = (values[0] if values else '') or ''

        # Base MCP docs URL (served by Sphinx for this app)
        base_url = self.DOCROOT + '/mcp.html'

        # Tools are documented in docs/source/mcp.md. Sphinx typically
        # normalizes heading IDs by lowercasing and replacing non-alphanumeric
        # characters with hyphens, so underscores in tool names become
        # hyphens. Mirror that here so anchors resolve correctly.
        normalized = tool_name.strip().lower()
        anchor_name = normalized.replace(' ', '-').replace('_', '-')
        url = f'{base_url}#{anchor_name}' if anchor_name else base_url

        try:
            self.open_link(url)
        except Exception:
            logger.error('Failed to open MCP documentation link: %s', url)

    def _attach_mcp_log_handler(self):
        """Attach one UI handler to multiple logger families."""
        ui_handler = MCPTextHandler(self.mcp_log)
        ui_handler.addFilter(MCPFilter())

        # Add to root logger so all MCP Filtered logs come here
        root_logger = logging.getLogger()  # Root
        root_logger.addHandler(ui_handler)

        # # Attach to the three families so we actually receive their records
        # logging.getLogger("oci-policy-analysis.mcp").addHandler(ui_handler)
        # logging.getLogger("fastmcp").addHandler(ui_handler)
        # logging.getLogger("uvicorn").addHandler(ui_handler)

        # Keep a reference so GC doesn't drop it
        self._mcp_ui_handler = ui_handler
        logger.info('MCP tab handler attached to oci-policy-analysis.mcp, oci-policy-analysis.mcp_server')

    def _start_mcp(self):
        if self.server_running:
            messagebox.showinfo('MCP', 'MCP server is already running.')
            return
        mcp_server.pca = self.policy_repo
        # Need to create simulation engine here as well
        mcp_server.sim_engine = PolicySimulationEngine(
            policy_repo=self.policy_repo, ref_data_repo=self.policy_repo.permission_reference_repo
        )
        # Show the count of loaded policies in the simulation engine
        policy_count = len(self.policy_repo.regular_statements) if self.policy_repo else 0
        logger.info(f'Policy Analysis Repository and Simulation Engine initialized with {policy_count} policies.')
        # Show count of policies in the simulation engine
        logger.info('Starting MCP server...')
        start_mcp_server_in_thread(self.settings)
        self._set_status(True)

    def _set_status(self, running: bool):
        if running:
            self.status_lbl.config(text='Running', foreground='green')
            self.start_btn.config(state=tk.DISABLED)
        else:
            self.status_lbl.config(text='Stopped', foreground='red')
            self.start_btn.config(state=tk.NORMAL)

    def _start_status_poll(self):
        is_running = mcp_server_status()
        _previous = self.server_running
        self.server_running = is_running
        # logger.debug(f"MCP server is {'running' if is_running else 'stopped'}")
        self._set_status(is_running)
        self.after(5000, self._start_status_poll)

    def _toggle_debug(self):
        level = 'DEBUG' if self.debug_var.get() else 'INFO'

        # Our component loggers
        set_component_level('mcp_server', level)
        set_component_level('mcp_tab', level)

        # Third-party families (not under our hierarchy) — set directly
        # logging.getLogger('fastmcp').setLevel(getattr(logging, level))
        # logging.getLogger('uvicorn').setLevel(getattr(logging, level))

        logger.info(f'Set MCP-related loggers to {level}')

    # -------------------------
    # Tools list from static resource
    # -------------------------

    def _load_static_tools_from_resource(self) -> None:
        """Load MCP tools metadata from a packaged JSON resource, if present.

        This uses the `mcp_tools.json` file included with the application as
        a static description of available MCP tools (name, description,
        inputSchema, outputSchema). It does not require the MCP server to be
        running and serves as the primary source for the tools table.
        """

        try:
            # Try to read mcp_tools.json from the installed package resources
            with resources.files('oci_policy_analysis.logic.mcp_tools_list').joinpath('mcp_tools.json').open(
                'r', encoding='utf-8'
            ) as fp:  # type: ignore[attr-defined]
                raw = fp.read()
            data = json.loads(raw)
            result = data.get('result') or {}
            tools_raw = result.get('tools') or []
            tools: list[dict] = []
            for t in tools_raw:
                if not isinstance(t, dict):
                    continue
                name = t.get('name', '')
                desc = t.get('description', '')
                input_schema = t.get('inputSchema') or t.get('input_schema') or {}
                output_schema = t.get('outputSchema') or t.get('output_schema') or {}
                try:
                    inputs = ', '.join((input_schema.get('properties') or {}).keys())
                except Exception:
                    inputs = ''
                try:
                    outputs = ', '.join((output_schema.get('properties') or {}).keys())
                except Exception:
                    outputs = ''
                tools.append(
                    {
                        'name': name,
                        'description': desc,
                        'inputs': inputs,
                        'outputs': outputs,
                    }
                )
            logger.info('Loaded %d static MCP tools from packaged mcp_tools.json', len(tools))
            if tools:
                self._populate_tools_table(tools)
        except FileNotFoundError:
            logger.info('No packaged mcp_tools.json resource found; MCP tools table will rely on live data only.')
        except Exception as exc:
            logger.error('Failed to load static MCP tools from resource: %s', exc, exc_info=True)
