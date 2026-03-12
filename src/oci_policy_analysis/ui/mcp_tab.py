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

import logging
import tkinter as tk
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

    def _build_ui(self):
        ttk.Label(self, text='MCP Server Control').pack(pady=10)
        ctrl_frame = ttk.Frame(self)
        ctrl_frame.pack(pady=10)

        self.start_btn = ttk.Button(ctrl_frame, text='Start MCP Server', command=self._start_mcp)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        ttk.Label(ctrl_frame, text='Status:').pack(side=tk.LEFT, padx=(15, 0))
        self.status_lbl = ttk.Label(ctrl_frame, text='Stopped', foreground='red')
        self.status_lbl.pack(side=tk.LEFT)

        self.debug_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self, text='Enable MCP Debug Logging', variable=self.debug_var, command=self._toggle_debug
        ).pack(pady=4)

        ttk.Label(self, text='MCP Server Log:').pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.mcp_log = ScrolledText(self, height=14, width=100, wrap='word', font=('Consolas', 10))
        self.mcp_log.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.mcp_log.insert(tk.END, 'MCP log output will appear here...\n')

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
