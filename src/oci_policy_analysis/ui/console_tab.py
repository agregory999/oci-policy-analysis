##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# console_tab.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

import logging
import queue
import sys
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from oci_policy_analysis.common.logger import get_logger, set_component_level, set_log_level

# Logger for this module
logger = get_logger('console_tab')


# Dedicated UI handler (unfiltered, shows everything)
class ConsoleTextHandler(logging.Handler):
    """
    Thread-safe handler for Console tab (batched, no filter).
    Appends log messages to a Tkinter Text widget.
    """

    def __init__(self, text_widget: ScrolledText):
        super().__init__(level=logging.INFO)  # Force INFO and above
        self.text_widget = text_widget
        self.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] [%(name)s] %(message)s'))
        self.queue = queue.Queue()  # Thread-safe queue for batching
        self.text_widget.after(200, self._flush)  # Slower poll to reduce overhead

    def emit(self, record):
        try:
            # No UI skip/filter here (shows everything, but recursion risk low since embedded)
            msg = self.format(record)
            self.queue.put(msg)  # Non-blocking put to queue
        except Exception as e:
            print(f'Emit error: {e}', file=sys.stderr)  # To shell for debug

    def _flush(self):
        try:
            appended = 0
            while not self.queue.empty() and appended < 50:  # Batch limit per flush
                msg = self.queue.get_nowait()  # Non-blocking get
                self.text_widget.insert(tk.END, msg + '\n')
                appended += 1

            if appended > 0:
                self.text_widget.see(tk.END)  # Only see if we added something

            # Buffer limit: Delete oldest if too large
            lines = int(self.text_widget.index('end-1c').split('.')[0])
            if lines > 10000:
                self.text_widget.delete('1.0', f'{lines - 5000}.0')  # Keep last 5k lines

            # print(f"Flush called, appended {appended}", file=sys.stderr)  # Debug to shell (optional, remove if not needed)
        except queue.Empty:
            pass  # Normal if queue drained
        except Exception as e:
            print(f'Flush error: {e}', file=sys.stderr)  # Catch and report
        finally:
            self.text_widget.after(200, self._flush)  # Reschedule


class ConsoleTab(ttk.Frame):
    """
    Console Tab: Show all logs (unfiltered) with control of log level.
    Debug logs go to shell only. For this reason, the level selector excludes DEBUG.
    """

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app  # Reference to main App for shared vars (e.g., log_level_var)

        self._build_ui()
        self._attach_console_log_handler()

    def _build_ui(self):
        # ttk.Label(self, text='Console Log').pack(pady=10)
        ctrl_frame = ttk.Frame(self)
        ctrl_frame.pack(pady=10)

        ttk.Button(ctrl_frame, text='Clear', command=lambda: self.console_log.delete('1.0', tk.END)).pack(
            side=tk.LEFT, padx=5
        )

        # --- Global logger controls ---
        ttk.Label(ctrl_frame, text='Log Level (Debug only to shell):').pack(side=tk.LEFT, padx=(15, 0))
        level_combo = ttk.Combobox(
            ctrl_frame,
            textvariable=self.app.log_level_var,  # Reuse from App
            values=['INFO', 'WARNING', 'ERROR', 'CRITICAL'],
            width=10,
        )
        level_combo.pack(side=tk.LEFT)
        # Show/hide checkbox added here
        self.show_loggers_var = tk.BooleanVar(value=True)
        show_loggers_chk = ttk.Checkbutton(
            ctrl_frame, text='Show loggers', variable=self.show_loggers_var, command=self._toggle_logger_grid
        )
        show_loggers_chk.pack(side=tk.LEFT, padx=10)

        # --- Individual logger controls: grid layout in a separate frame ---
        self.logger_components = [
            'cli',
            'caching',
            'mcp_server',
            'config',
            'main',
            'reference_data_repo',
            'ai_repo',
            'policy_parser',
            'data_repo',
            'console_tab',
            'resource_principals_tab',
            'condition_tester_tab',
            'policies',
            'report_tab',
            'permissions_report',
            'data_table',
            'historical_tab',
            'dynamic_group_tab',
            'settings',
            'mcp_tab',
            'cross_tenancy_tab',
            'policy_overlap',
            'maintenance',
            'users_tab',
        ]
        self.logger_level_vars = {}

        # --- Console Output Display ---
        ttk.Label(self, text='All Logs (INFO+):').pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.console_log = ScrolledText(self, height=14, width=100, wrap='word', font=('Consolas', 10))
        self.console_log.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.console_log.insert(tk.END, 'Console log output will appear here...\n')

        # Frame for loggers grid, packed BELOW log window
        self.logger_grid_frame = ttk.Frame(self)
        self.logger_grid_frame.pack(pady=(0, 10), padx=8, anchor='w')

        per_row = 6
        for idx, comp in enumerate(self.logger_components):
            row, col = divmod(idx, per_row)
            var = tk.StringVar()
            import logging

            lg = logging.getLogger(f'oci-policy-analysis.{comp}')
            level = logging.getLevelName(lg.level if lg.level != 0 else logging.getLogger().level)
            if level not in ['INFO', 'WARNING', 'ERROR', 'CRITICAL']:
                level = 'INFO'
            var.set(level)
            self.logger_level_vars[comp] = var
            lbl = ttk.Label(self.logger_grid_frame, text=comp)
            lbl.grid(row=row, column=col * 2, sticky='e', padx=(4, 1), pady=2)
            combo = ttk.Combobox(
                self.logger_grid_frame,
                textvariable=var,
                values=['INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                width=8,
            )
            combo.grid(row=row, column=col * 2 + 1, sticky='w', padx=(1, 8), pady=2)
            combo.bind('<<ComboboxSelected>>', lambda e, c=comp, v=var: set_component_level(c, v.get()))
        # Store for syncing when global is changed
        self._logger_combo_vars = self.logger_level_vars

        def global_log_level_changed(event=None):
            new_level = self.app.log_level_var.get()
            set_log_level(new_level)
            for comp, var in self._logger_combo_vars.items():
                var.set(new_level)
                set_component_level(comp, new_level)

        level_combo.bind('<<ComboboxSelected>>', global_log_level_changed)

        # # --- Console Output Display ---
        # ttk.Label(self, text='All Logs (INFO+):').pack(anchor=tk.W, padx=10, pady=(10, 0))
        # self.console_log = ScrolledText(self, height=14, width=100, wrap='word', font=('Consolas', 10))
        # self.console_log.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        # self.console_log.insert(tk.END, 'Console log output will appear here...\n')

    def _toggle_logger_grid(self):
        if self.show_loggers_var.get():
            self.logger_grid_frame.pack(pady=(0, 10), padx=8, anchor='w')
        else:
            self.logger_grid_frame.pack_forget()

    def _attach_console_log_handler(self):
        """Attach handler to root (unfiltered)."""
        ui_handler = ConsoleTextHandler(self.console_log)

        root_logger = logging.getLogger()  # Root
        root_logger.addHandler(ui_handler)

        # Keep a reference so GC doesn't drop it
        self._console_ui_handler = ui_handler
        logger.info('Console tab handler attached to root (unfiltered).')
