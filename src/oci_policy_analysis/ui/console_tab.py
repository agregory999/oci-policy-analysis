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
# Supports Python 3.11 and above
#
# coding: utf-8
##########################################################################

import logging
import queue
import sys
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from oci_policy_analysis.logger import get_logger


# Dedicated UI handler (unfiltered, shows everything)
class ConsoleTextHandler(logging.Handler):
    """Thread-safe handler for Console tab (batched, no filter)."""

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


logger = get_logger('console_tab')


class ConsoleTab(ttk.Frame):
    """Console Tab: Show all logs (unfiltered) with controls."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app  # Reference to main App for shared vars (e.g., log_level_var)

        self._build_ui()
        self._attach_console_log_handler()

    def _build_ui(self):
        ttk.Label(self, text='Console Log').pack(pady=10)
        ctrl_frame = ttk.Frame(self)
        ctrl_frame.pack(pady=10)

        ttk.Button(ctrl_frame, text='Clear', command=lambda: self.console_log.delete('1.0', tk.END)).pack(
            side=tk.LEFT, padx=5
        )

        ttk.Label(ctrl_frame, text='Log Level (Debug only to shell):').pack(side=tk.LEFT, padx=(15, 0))
        level_combo = ttk.Combobox(
            ctrl_frame,
            textvariable=self.app.log_level_var,  # Reuse from App
            values=['INFO', 'WARNING', 'ERROR', 'CRITICAL'],
            # state="readonly",
            width=10,
        )
        level_combo.pack(side=tk.LEFT)
        # level_combo.bind("<<ComboboxSelected>>", lambda e: self.app._apply_log_level(level=level_combo.get()))  # Reuse App's method
        level_combo.bind('<<ComboboxSelected>>', self.app._apply_log_level)  # Reuse App's method

        ttk.Label(self, text='All Logs (INFO+):').pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.console_log = ScrolledText(self, height=14, width=100, wrap='word', font=('Consolas', 10))
        self.console_log.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.console_log.insert(tk.END, 'Console log output will appear here...\n')

    def _attach_console_log_handler(self):
        """Attach handler to root (unfiltered)."""
        ui_handler = ConsoleTextHandler(self.console_log)

        root_logger = logging.getLogger()  # Root
        root_logger.addHandler(ui_handler)

        # Keep a reference so GC doesn't drop it
        self._console_ui_handler = ui_handler
        logger.info('Console tab handler attached to root (unfiltered).')
