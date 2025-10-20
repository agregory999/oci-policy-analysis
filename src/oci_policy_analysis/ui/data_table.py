##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# data_table.py
#
# @author: Andrew Gregory
#
# Supports Python 3.11 and above
#
# coding: utf-8
##########################################################################
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from oci_policy_analysis.logic.logger import get_logger

logger = get_logger(component='data_table')


class DataTable(tk.Frame):
    """A Tkinter table widget with alternating row colors, sortable columns, resizable columns, show/hide columns, row selection with callback, full space utilization, cell copy functionality, and row context menu.

    Note: ttk.Treeview does not natively support multi-line text wrapping. Text with newlines may appear clipped; use wider columns (via column_widths) for better visibility. Font, padding, and ttk.Style must be configured externally to include right-side cell padding (e.g., padding=(0, 0, 5, 0)) for column separation.

    Attributes:
        parent: The parent Tkinter widget.
        columns: List of all possible column names.
        display_columns: List of initially displayed column names.
        data: List of dictionaries containing row data.
        sortable: Enable/disable column sorting (default: True).
        row_colors: Tuple of colors for alternating rows (default: white, light gray).
        selection_callback: Optional function to call with selected rows (default: None). Can be omitted if no callback is needed.
        multi_select: Enable/disable multi-row selection (default: False).
        column_widths: Dictionary mapping column names to initial widths (default: None, uses 100 for all columns).
        row_context_menu_callback: Optional function to create a context menu for a row (default: None).
    """

    def __init__(
        self,
        parent: tk.Widget,
        columns: list[str],
        display_columns: list[str],
        data: list[dict],
        sortable: bool = True,
        row_colors: tuple[str, str] = ('#FFFFFF', '#F0F0F0'),
        selection_callback: Callable[[list[dict]], None] | None = None,
        multi_select: bool = False,
        column_widths: dict[str, int] | None = None,
        row_context_menu_callback: Callable[[int], tk.Menu] | None = None,
    ) -> None:
        super().__init__(parent)
        logger.debug('Initializing DataTable with %d columns and %d rows', len(columns), len(data))

        self.all_columns = columns
        self.display_columns = display_columns
        self.data = data
        self.sortable = sortable
        self.row_colors = row_colors
        self.sort_directions: dict[str, bool] = {col: False for col in columns}
        self.hidden_columns = set(columns) - set(display_columns)
        self.column_widths: dict[str, int] = (
            column_widths if column_widths is not None else {col: 100 for col in columns}
        )
        self.min_width = 50
        self.max_width = 300
        self.resizing_column: str | None = None
        self.selection_callback = selection_callback
        self.multi_select = multi_select
        self.row_context_menu_callback = row_context_menu_callback
        self.data_map: dict[str, int] = {}
        self.selected_cell: tuple[str, int] | None = None  # (column, row_index)

        # Configure frame to expand in grid layout
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Validate display_columns and column_widths
        if not set(display_columns).issubset(columns):
            logger.error('Invalid display_columns: %s', display_columns)
            raise ValueError('All display_columns must be in columns')
        if column_widths is not None and not set(column_widths.keys()).issubset(columns):
            logger.error('Invalid column_widths keys: %s', column_widths.keys())
            raise ValueError('All column_widths keys must be in columns')

        self._setup_ui()
        logger.debug('UI setup completed')

    def _setup_ui(self) -> None:
        """Set up the table UI with headers, data rows, and selection handling."""
        # Main frame for table
        self.table_frame = tk.Frame(self)
        self.table_frame.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
        self.table_frame.grid_rowconfigure(0, weight=1)
        self.table_frame.grid_columnconfigure(0, weight=1)

        # Configure Treeview
        self.tree = ttk.Treeview(
            self.table_frame,
            columns=self.display_columns,
            show='headings',
            selectmode='extended' if self.multi_select else 'browse',
        )
        self.tree.grid(row=0, column=0, sticky='nsew')
        logger.debug('Treeview configured with %d columns', len(self.display_columns))

        # Configure scrollbars
        vsb = ttk.Scrollbar(self.table_frame, orient='vertical', command=self.tree.yview)
        vsb.grid(row=0, column=1, sticky='ns')
        self.tree.configure(yscrollcommand=vsb.set)

        hsb = ttk.Scrollbar(self.table_frame, orient='horizontal', command=self.tree.xview)
        hsb.grid(row=1, column=0, sticky='ew')
        self.tree.configure(xscrollcommand=hsb.set)

        # Configure column headers
        for col in self.display_columns:
            self.tree.heading(col, text=col, anchor='w', command=lambda c=col: self._sort_column(c))
            self.tree.column(col, anchor='w', width=self.column_widths[col], minwidth=self.min_width, stretch=False)

        # Configure alternating row colors
        self.tree.tag_configure('oddrow', background=self.row_colors[1])
        self.tree.tag_configure('evenrow', background=self.row_colors[0])

        # Populate data
        self._populate_data()

        # Bind events
        self.tree.bind('<ButtonPress-1>', self._start_resize)
        self.tree.bind('<B1-Motion>', self._resize_column)
        self.tree.bind('<ButtonRelease-1>', self._end_resize)
        self.tree.bind('<<TreeviewSelect>>', self._on_selection)
        self.tree.bind('<Button-1>', self._select_cell)
        self.tree.bind('<Control-c>', self._copy_cell)  # Ctrl+C for Windows/Linux
        self.tree.bind('<Command-c>', self._copy_cell)  # Command+C for macOS
        self.tree.bind('<Button-3>', self._show_context_menu)

        # Initial column update
        self._update_columns()

    def _populate_data(self) -> None:
        """Populate the table with data, applying alternating row colors."""
        logger.debug('Populating table with %d rows', len(self.data))
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.data_map.clear()
        for i, row in enumerate(self.data):
            tag = 'evenrow' if i % 2 == 0 else 'oddrow'
            values = [row.get(col, '') for col in self.tree['columns']]
            item_id = self.tree.insert('', 'end', values=values, tags=(tag,))
            self.data_map[item_id] = i

    def _sort_column(self, col: str) -> None:
        """Sort the table by the specified column and update indicators."""
        if not self.sortable or col not in self.tree['columns']:
            logger.debug('Sorting skipped: column %s not sortable or not visible', col)
            return

        logger.debug('Sorting column %s', col)
        self.sort_directions[col] = not self.sort_directions[col]
        reverse = self.sort_directions[col]

        try:
            self.data.sort(key=lambda x: x.get(col, ''), reverse=reverse)
        except (ValueError, TypeError):
            self.data.sort(key=lambda x: str(x.get(col, '')), reverse=reverse)

        for c in self.tree['columns']:
            self.tree.heading(c, text=c, anchor='w')
        indicator = ' ▼' if reverse else ' ▲'
        self.tree.heading(col, text=f'{col}{indicator}', anchor='w')

        self._populate_data()
        logger.info('Table sorted by %s (%s)', col, 'descending' if reverse else 'ascending')

    def _start_resize(self, event: tk.Event) -> str | None:
        """Start column resizing."""
        if self.tree.identify_region(event.x, event.y) != 'separator':
            return None
        col = self.tree.identify_column(event.x)
        col_index = int(col.replace('#', '')) - 1
        if col_index >= len(self.tree['columns']):
            logger.debug('Invalid column index for resize: %d', col_index)
            return None
        self.resizing_column = self.tree['columns'][col_index]
        self.resize_start_x = event.x_root
        logger.debug('Starting resize for column %s', self.resizing_column)
        return 'break'

    def _resize_column(self, event: tk.Event) -> None:
        """Handle column resizing without affecting other columns."""
        if not self.resizing_column:
            return
        delta = event.x_root - self.resize_start_x
        new_width = max(self.min_width, min(self.max_width, self.column_widths[self.resizing_column] + delta))
        self.column_widths[self.resizing_column] = new_width
        self.tree.column(self.resizing_column, width=new_width, stretch=False)
        self.resize_start_x = event.x_root
        logger.debug('Resizing column %s to width %d', self.resizing_column, new_width)

    def _end_resize(self, event: tk.Event) -> None:
        """End column resizing."""
        if self.resizing_column:
            logger.info(
                'Finished resizing column %s to width %d',
                self.resizing_column,
                self.column_widths[self.resizing_column],
            )
        self.resizing_column = None

    def _show_context_menu(self, event: tk.Event) -> None:
        """Show context menu for column show/hide or row actions."""
        region = self.tree.identify_region(event.x, event.y)
        if region == 'heading':
            col = self.tree.identify_column(event.x)
            if not col:
                return
            col_index = int(col.replace('#', '')) - 1
            if col_index >= len(self.tree['columns']):
                return
            self.selected_column = self.tree['columns'][col_index]
            self.context_menu.entryconfigure(
                'Hide Column', state='normal' if self.selected_column not in self.hidden_columns else 'disabled'
            )
            self.context_menu.post(event.x_root, event.y_root)
            logger.debug('Showing column context menu for %s', self.selected_column)
        elif region == 'cell' and self.row_context_menu_callback:
            item = self.tree.identify_row(event.y)
            if item and item in self.data_map:
                row_index = self.data_map[item]
                menu = self.row_context_menu_callback(row_index)
                if menu:
                    menu.post(event.x_root, event.y_root)
                    logger.debug('Showing row context menu for row %d', row_index)

    def _select_cell(self, event: tk.Event) -> None:
        """Select a cell for copying."""
        region = self.tree.identify_region(event.x, event.y)
        if region != 'cell':
            self.selected_cell = None
            return
        item = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if item and col:
            col_index = int(col.replace('#', '')) - 1
            if col_index < len(self.tree['columns']):
                self.selected_cell = (self.tree['columns'][col_index], self.data_map.get(item, -1))
                logger.debug('Selected cell: column=%s, row_index=%d', *self.selected_cell)

    def _copy_cell(self, event: tk.Event) -> str | None:
        """Copy the selected cell's content to the clipboard."""
        if not self.selected_cell or self.selected_cell[1] == -1:
            logger.debug('No cell selected for copying')
            return None
        col, row_index = self.selected_cell
        value = str(self.data[row_index].get(col, ''))
        self.clipboard_clear()
        self.clipboard_append(value)
        logger.info('Copied cell value: %s', value)
        return 'break'

    def _hide_column(self) -> None:
        """Hide the selected column."""
        if hasattr(self, 'selected_column') and self.selected_column not in self.hidden_columns:
            self.hidden_columns.add(self.selected_column)
            self._update_columns()
            logger.info('Hid column %s', self.selected_column)

    def _show_column(self, col: str) -> None:
        """Show a previously hidden column."""
        if col in self.hidden_columns:
            self.hidden_columns.remove(col)
            self._update_columns()
            logger.info('Showed column %s', col)

    def _update_columns(self) -> None:
        """Update displayed columns in the Treeview."""
        visible_columns = [col for col in self.all_columns if col not in self.hidden_columns]
        self.tree.configure(columns=visible_columns)
        sorted_col = next((col for col, reverse in self.sort_directions.items() if reverse), None)
        for col in visible_columns:
            indicator = ' ▼' if sorted_col == col and self.sort_directions[col] else ''
            self.tree.heading(col, text=f'{col}{indicator}', anchor='w', command=lambda c=col: self._sort_column(c))
            self.tree.column(col, anchor='w', width=self.column_widths[col], stretch=False)
        self._populate_data()
        logger.debug('Updated columns: %d visible', len(visible_columns))

    def set_multi_select(self, multi_select: bool) -> None:
        """Set single or multi-select mode."""
        self.multi_select = multi_select
        self.tree.configure(selectmode='extended' if multi_select else 'browse')
        logger.info('Selection mode set to %s', 'multi-select' if multi_select else 'single-select')

    def set_display_columns(self, display_columns: list[str]) -> None:
        """Set the displayed columns externally."""
        if not set(display_columns).issubset(self.all_columns):
            logger.error('Invalid display_columns: %s', display_columns)
            raise ValueError('All display_columns must be in columns')
        self.display_columns = display_columns
        self.hidden_columns = set(self.all_columns) - set(display_columns)
        self._update_columns()
        logger.debug('Set display columns: %s', display_columns)

    def _on_selection(self, event: tk.Event) -> None:
        """Handle row selection and trigger callback."""
        if not self.selection_callback:
            return
        selected_items = self.tree.selection()
        selected_rows = [self.data[self.data_map[item]] for item in selected_items if item in self.data_map]
        self.selection_callback(selected_rows)
        logger.debug('Selected %d rows', len(selected_rows))

    def update_data(self, new_data: list[dict]) -> None:
        """Update table data and refresh display.

        Args:
            new_data: List of dictionaries containing new row data.
        """
        logger.debug('Updating data with %d rows', len(new_data))
        self.data = new_data
        self._populate_data()
