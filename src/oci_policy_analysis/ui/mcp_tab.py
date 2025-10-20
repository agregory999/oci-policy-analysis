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
# Supports Python 3.11 and above
#
# coding: utf-8
##########################################################################


import logging
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import oci_policy_analysis.logic.mcp_server as mcp_server
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository
from oci_policy_analysis.logic.logger import get_logger
from oci_policy_analysis.logic.mcp_server import server_thread, start_mcp_server_in_thread, stop_mcp_server

logger = get_logger(component='mcp_tab')


class MCPHandler(logging.Handler):
    """Minimal handler that writes MCP log lines to a ScrolledText widget."""

    def __init__(self, text_widget: ScrolledText, prefix_filter='oci-policy-analysis.MCP'):
        super().__init__()
        self.text_widget = text_widget
        self.prefix_filter = prefix_filter
        self.formatter = logging.Formatter('%(asctime)s [%(levelname)s] [%(name)s] %(message)s')

    def emit(self, record):
        # Filter by logger prefix (only MCP logs)
        if not record.name.startswith(self.prefix_filter):
            return

        msg = self.format(record)
        # Tkinter must update from main thread
        self.text_widget.after(0, self._append, msg)

    def _append(self, msg: str):
        self.text_widget.insert(tk.END, msg + '\n')
        self.text_widget.see(tk.END)


class McpTab(ttk.Frame):
    """
    Minimal MCP Tab: Start / Stop the MCP server and show status.
    Uses the already-loaded data_repo from memory.
    """

    def __init__(self, parent, app, policy_repo: PolicyAnalysisRepository, settings):
        """
        Args:
            parent: parent notebook or frame
            config: dict from config.json (must include mcp settings)
            log_console: existing popup console (must have .write_line)
        """
        super().__init__(parent)
        self.app = app
        self.settings = settings
        self.policy_repo = policy_repo
        self.server_running = False

        self._build_ui()
        self._start_status_poll()
        self._attach_mcp_log_handler()

    def _build_ui(self):
        header = ttk.Label(self, text='MCP Server Control')
        header.pack(pady=10)

        # --- Start/Stop frame ---
        ctrl_frame = ttk.Frame(self)
        ctrl_frame.pack(pady=10)

        self.start_btn = ttk.Button(ctrl_frame, text='Start MCP Server', command=self.start_mcp)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = ttk.Button(ctrl_frame, text='Stop MCP Server', command=self.stop_mcp, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        ttk.Label(ctrl_frame, text='Status:').pack(side=tk.LEFT, padx=(15, 0))
        self.status_lbl = ttk.Label(ctrl_frame, text='Stopped', foreground='red')
        self.status_lbl.pack(side=tk.LEFT)

        # --- MCP log area ---
        ttk.Label(self, text='MCP Server Log:').pack(anchor=tk.W, padx=10, pady=(10, 0))

        self.mcp_log = ScrolledText(
            self,
            height=14,
            width=100,
            wrap='word',
            state='normal',
            bg='#FFFFFF',
            fg='#000000',
            font=('Consolas', 10),
        )

        # self.mcp_log = ScrolledText(self, height=12, width=100, state=tk.NORMAL)
        self.mcp_log.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.mcp_log.insert(tk.END, 'MCP log output will appear here...\n')

    # ---------------------------
    # MCP Server Controls
    # ---------------------------

    def start_mcp(self):
        if self.server_running:
            messagebox.showinfo('MCP', 'MCP server is already running.')
            return

        # Start MCP in background thread
        mcp_server.pca = self.policy_repo
        logger.info('Starting MCP server...')
        start_mcp_server_in_thread(self.settings)
        self._set_status(running=True)

    def stop_mcp(self):
        if not self.server_running:
            messagebox.showinfo('MCP', 'MCP server is not running.')
            return

        logger.info('Stopping MCP server...')
        stop_mcp_server()
        self._set_status(running=False)

    # ---------------------------
    # Status Handling
    # ---------------------------

    def _set_status(self, running: bool):
        self.server_running = running
        if running:
            self.status_lbl.config(text='Running', foreground='green')
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
        else:
            self.status_lbl.config(text='Stopped', foreground='red')
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)

    # ---------------------------
    # Poll for status
    # ---------------------------

    def _start_status_poll(self):
        self._check_status()
        self.after(3000, self._start_status_poll)

    def _check_status(self):
        """Update label if MCP thread changes."""
        try:
            alive = bool(server_thread and server_thread.is_alive())
        except Exception:
            alive = False
        if alive != self.server_running:
            self._set_status(alive)

    # ---------------------------
    # Log Handling
    # ---------------------------
    def _attach_mcp_log_handler(self):
        """Attach a logging handler to the MCP log area."""

        handler = MCPHandler(self.mcp_log, prefix_filter='oci-policy-analysis.MCP')
        base_logger = logging.getLogger('oci-policy-analysis')
        base_logger.addHandler(handler)
        self.mcp_handler = handler
