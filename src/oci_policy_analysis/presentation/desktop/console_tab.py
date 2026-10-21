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

from oci_policy_analysis.application.core.support.logger import get_logger, set_component_level, set_log_level
from oci_policy_analysis.application.services.logging_service import LoggingService
from oci_policy_analysis.presentation.desktop.base_tab import BaseUITab

# Logger for this module
logger = get_logger(component='presentation.desktop.console_tab')


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


class ConsoleTab(BaseUITab):
    """
    Console Tab: Show all logs (unfiltered) with control of log level.
    Debug logs go to shell only. For this reason, the level selector excludes DEBUG.
    """

    def __init__(self, parent, app):
        super().__init__(
            parent,
            default_help_text=(
                'View and interact with raw logs. '
                'Use controls below to filter log output, clear, or adjust logging levels. '
                'For troubleshooting help, see the docs link.'
            ),
            page_help_link='/logging_and_troubleshooting.html',
        )
        self.app = app  # Reference to main App for shared vars (e.g., log_level_var)

        self._build_ui()
        self._attach_console_log_handler()

    def _build_ui(self):  # noqa: C901
        top_frame = ttk.Frame(self)
        top_frame.pack(fill=tk.X, padx=5, pady=(8, 0))

        # Detect if verbose mode is active
        verbose_active = self.app.log_level_var.get() == 'DEBUG'

        if verbose_active:
            banner = ttk.Label(
                top_frame,
                text=(
                    'Verbose mode (--verbose) is active. Only INFO+ logs appear below, but DEBUG output is available in the shell and app.log file.\n'
                    'No logging configuration changes are allowed during this session. To modify logging, restart without --verbose.'
                ),
                foreground='red',
                justify='left',
                padding=6,
                font=('Arial', 11, 'bold'),
            )
            banner.pack(anchor=tk.W, pady=(0, 9))

        ctrl_frame = ttk.Frame(self)
        ctrl_frame.pack(pady=10)

        clear_btn = ttk.Button(
            ctrl_frame, text='Clear Console Tab', command=lambda: self.console_log.delete('1.0', tk.END)
        )
        clear_btn.pack(side=tk.LEFT, padx=5)

        # --- Global logger controls ---
        ttk.Label(ctrl_frame, text='Log Level (Debug only to shell):').pack(side=tk.LEFT, padx=(15, 0))
        level_combo = ttk.Combobox(
            ctrl_frame,
            textvariable=self.app.log_level_var,
            values=['INFO', 'WARNING', 'ERROR', 'CRITICAL'],
            width=10,
            state='disabled' if verbose_active else 'readonly',
        )
        level_combo.pack(side=tk.LEFT)
        # Show/hide checkbox added here
        self.show_loggers_var = tk.BooleanVar(value=False)
        show_loggers_chk = ttk.Checkbutton(
            ctrl_frame,
            text='Configure Component Loggers (as override to global level)',
            variable=self.show_loggers_var,
            command=self._toggle_logger_grid,
            state='disabled' if verbose_active else 'normal',
        )
        show_loggers_chk.pack(side=tk.LEFT, padx=10)

        from oci_policy_analysis.presentation.desktop.api_calls_window import ApiCallsWindow

        ttk.Button(self, text='API Calls · Current Session…', command=lambda: ApiCallsWindow(self)).pack(
            anchor='w', padx=10, pady=4
        )

        # --- Extra Logging Settings: Always Log Timings / API Calls ---
        from oci_policy_analysis.application.core.support import config as opa_config

        self.always_log_timings_var = tk.BooleanVar(value=bool(self.app.settings.get('always_log_timings', False)))
        self.always_log_api_calls_var = tk.BooleanVar(value=bool(self.app.settings.get('always_log_api_calls', False)))

        def _on_timings_toggle():
            self.app.settings['always_log_timings'] = bool(self.always_log_timings_var.get())
            opa_config.save_settings(self.app.settings)

        def _on_api_calls_toggle():
            self.app.settings['always_log_api_calls'] = bool(self.always_log_api_calls_var.get())
            opa_config.save_settings(self.app.settings)

        timings_chk = ttk.Checkbutton(
            ctrl_frame,
            text='Always Log Timings (CRITICAL)',
            variable=self.always_log_timings_var,
            command=_on_timings_toggle,
            state='disabled' if verbose_active else 'normal',
        )
        timings_chk.pack(side=tk.LEFT, padx=10)
        api_calls_chk = ttk.Checkbutton(
            ctrl_frame,
            text='Always Log API Calls (CRITICAL)',
            variable=self.always_log_api_calls_var,
            command=_on_api_calls_toggle,
            state='disabled' if verbose_active else 'normal',
        )
        api_calls_chk.pack(side=tk.LEFT, padx=10)

        # --- Individual logger controls: grid layout in a separate frame ---
        # Package mapping for loggers
        logging_settings = LoggingService(self.app.settings).get_log_settings()
        self.app.settings['log_levels'] = dict(logging_settings.get('log_levels', {}))
        self.logger_components_by_pkg = {
            'Platform': [
                'cli',
                'main',
                'mcp_server',
                'web_routes',
                'web_auth',
                'caching',
                'config',
                'logger',
                'usage_tracking',
            ],
            'Core Repo / Engine / Parser': [
                'core.repo.policy_analysis_repository',
                'core.repo.reference_data_repo',
                'core.engine.policy_intelligence_engine',
                'core.engine.policy_simulation_engine',
                'core.engine.consolidation_engine',
                'core.policy_corpus',
                'core.cross_tenancy_corpus',
                'cross_tenancy',
                'core.parser.policy_statement_normalizer',
                'core.parser.policy_subject_parser',
                'core.parser.condition_evaluator',
                'core.parser.where_clause_evaluator',
                'core.parser.tag_condition_collector',
            ],
            'Application Services': [
                'application.services.analysis',
                'application.services.cache',
                'application.services.condition_tester',
                'application.services.consolidation_workbench',
                'application.services.historical_analysis',
                'application.services.intelligence',
                'application.services.load',
                'application.services.logging',
                'application.services.policy_browser',
                'application.services.policy_graph',
                'application.services.principal_analysis',
                'application.services.prospective_builder',
                'application.services.prospective_statements',
                'application.services.recommendations',
                'application.services.reference_data',
                'application.services.settings',
                'application.services.simulation',
            ],
            'UI': [
                'settings_tab',
                'policies_tab',
                'policy_browser_tab',
                'policy_graph_tab',
                'dynamic_group_tab',
                'users_tab',
                'workload_principals_tab',
                'historical_tab',
                'cross_tenancy_tab',
                'condition_tester_tab',
                'tag_based_access_tab',
                'permissions_report_tab',
                'simulation_tab',
                'policy_recommendations_tab',
                'limits_tab',
                'mcp_tab',
                'presentation.desktop.console_tab',
                'data_table',
                'prospective_editor_window',
                'consolidation_workbench_tab',
                'builder_helpers',
                'maintenance_tab',
            ],
        }
        # Flattened for batch logic
        self.logger_components = []
        for group in self.logger_components_by_pkg:
            self.logger_components.extend(self.logger_components_by_pkg[group])

        self.logger_level_vars = {}

        # --- Console Output Display ---
        ttk.Label(self, text='All Logs (INFO+):').pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.console_log = ScrolledText(self, height=14, width=100, wrap='word', font=('Consolas', 10))
        self.console_log.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.console_log.insert(tk.END, 'Console log output will appear here...\n')

        # Four fixed logger columns; scrolling keeps UI at the right on narrow windows.
        self.logger_panel = ttk.Frame(self)
        self.logger_canvas = tk.Canvas(self.logger_panel, height=320, highlightthickness=0)
        vertical = ttk.Scrollbar(self.logger_panel, command=self.logger_canvas.yview)
        horizontal = ttk.Scrollbar(self.logger_panel, orient='horizontal', command=self.logger_canvas.xview)
        self.logger_canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.logger_canvas.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        self.logger_panel.columnconfigure(0, weight=1)
        self.logger_panel.rowconfigure(0, weight=1)
        self.logger_grid_frame = ttk.Frame(self.logger_canvas)
        self._logger_window = self.logger_canvas.create_window(0, 0, window=self.logger_grid_frame, anchor='nw')
        self._logger_group_frames = []
        self.logger_canvas.bind('<Configure>', lambda event: self._layout_logger_groups(event.width))
        self.logger_grid_frame.bind(
            '<Configure>', lambda _e: self.logger_canvas.configure(scrollregion=self.logger_canvas.bbox('all'))
        )

        log_levels = logging_settings.get('log_levels', {})

        def on_logger_level_change(event, comp, var):
            val = var.get()
            set_component_level(comp, val)
            if 'log_levels' not in self.app.settings:
                self.app.settings['log_levels'] = {}
            self.app.settings['log_levels'][comp] = val
            from oci_policy_analysis.application.core.support import config

            config.save_settings(self.app.settings)

        for pkg, comps in self.logger_components_by_pkg.items():
            ncol = 1
            frame = ttk.LabelFrame(self.logger_grid_frame, text=pkg, padding=6)
            self._logger_group_frames.append(frame)
            for idx, comp in enumerate(comps):
                row, col = divmod(idx, ncol)
                var = tk.StringVar()
                import logging

                lg = logging.getLogger(f'oci-policy-analysis.{comp}')
                level = log_levels.get(comp) or logging.getLevelName(
                    lg.level if lg.level != 0 else logging.getLogger().level
                )
                if level not in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
                    level = 'INFO'
                var.set(level)
                self.logger_level_vars[comp] = var
                lbl = ttk.Label(frame, text=comp)
                lbl.grid(row=row + 1, column=col * 2, sticky='e', padx=(4, 1), pady=2)
                combo = ttk.Combobox(
                    frame,
                    textvariable=var,
                    values=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                    width=8,
                )
                combo.grid(row=row + 1, column=col * 2 + 1, sticky='w', padx=(1, 8), pady=2)
                combo.bind('<<ComboboxSelected>>', lambda e, c=comp, v=var: on_logger_level_change(e, c, v))
                # Only reflect state in UI; don't set log level at init
                # set_component_level(comp, level)  # NO OP at startup
            # Each group uses space equal to 2 * (width) columns

        # Store for syncing when global is changed
        self._logger_combo_vars = self.logger_level_vars

        def global_log_level_changed(event=None):
            new_level = self.app.log_level_var.get()
            # Save global level
            self.app.settings['global_log_level'] = new_level
            set_log_level(new_level)
            for comp, var in self._logger_combo_vars.items():
                var.set(new_level)
                set_component_level(comp, new_level)

            # Persist all in settings
            if 'log_levels' not in self.app.settings:
                self.app.settings['log_levels'] = {}
            # Save overrides as complete current state
            for comp, var in self._logger_combo_vars.items():
                self.app.settings['log_levels'][comp] = var.get()
            from oci_policy_analysis.application.core.support import config

            config.save_settings(self.app.settings)

        # On startup: only reflect/restore UI state; don't set loggers
        global_level = logging_settings.get('global_log_level') or self.app.settings.get('global_log_level')
        if global_level:
            self.app.log_level_var.set(global_level)
        for comp, var in self.logger_level_vars.items():
            level = log_levels.get(comp)
            if level:
                var.set(level)

        # Ensure global level combo DOES NOT INCLUDE DEBUG
        level_combo['values'] = ['INFO', 'WARNING', 'ERROR', 'CRITICAL']
        level_combo.bind('<<ComboboxSelected>>', global_log_level_changed)

        # # --- Console Output Display ---
        # ttk.Label(self, text='All Logs (INFO+):').pack(anchor=tk.W, padx=10, pady=(10, 0))
        # self.console_log = ScrolledText(self, height=14, width=100, wrap='word', font=('Consolas', 10))
        # self.console_log.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        # self.console_log.insert(tk.END, 'Console log output will appear here...\n')

    def _layout_logger_groups(self, width):
        """Keep four category columns on one row, with UI always on the right."""
        requested_widths = [frame.winfo_reqwidth() + 12 for frame in self._logger_group_frames]
        content_width = max(width, sum(requested_widths))
        extra_width = (content_width - sum(requested_widths)) / max(len(requested_widths), 1)
        left = 0
        for frame, requested in zip(self._logger_group_frames, requested_widths, strict=True):
            column_width = requested + extra_width
            frame.place(x=left + 6, y=6, width=column_width - 12)
            left += column_width
        content_height = max((frame.winfo_reqheight() for frame in self._logger_group_frames), default=1) + 12
        self.logger_canvas.itemconfigure(self._logger_window, width=content_width, height=content_height)

    def _toggle_logger_grid(self):
        if self.show_loggers_var.get():
            self.logger_panel.pack(fill='both', expand=True, pady=(0, 10), padx=8)
            self._layout_logger_groups(self.logger_canvas.winfo_width())
        else:
            self.logger_panel.pack_forget()

    def _attach_console_log_handler(self):
        """Attach handler to root (unfiltered)."""
        ui_handler = ConsoleTextHandler(self.console_log)

        # Always filter handler to INFO+ so DEBUG never appears in ConsoleTab (even with root/component at DEBUG)
        import logging as _logging

        ui_handler.setLevel(_logging.INFO)

        root_logger = logging.getLogger()  # Root
        root_logger.addHandler(ui_handler)

        # Keep a reference so GC doesn't drop it
        self._console_ui_handler = ui_handler
        logger.info('Console tab handler attached to root (unfiltered).')
