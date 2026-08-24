"""Desktop UI for on-demand reports."""

from __future__ import annotations

import json
import tkinter as tk
import tkinter.filedialog as tkfiledialog
import tkinter.messagebox
from tkinter import ttk

from tkhtmlview import HTMLText

from oci_policy_analysis.application.services.reports_service import ReportsService
from oci_policy_analysis.presentation.desktop.base_tab import BaseUITab


class ReportsTab(BaseUITab):
    """Present report generation, format preview, and download controls."""

    def __init__(self, parent: tk.Widget, app: object) -> None:
        """Initialize the reports tab."""
        super().__init__(
            parent,
            default_help_text=(
                'Generate reports on demand. Reports do not run during normal policy analysis; '
                'choose JSON, Markdown, or rendered HTML for preview and export.'
            ),
            page_help_link='/reports.html',
        )
        self.app = app
        self._report: dict | None = None
        controls = ttk.LabelFrame(self, text='Available Reports')
        controls.pack(fill='x', padx=10, pady=10)
        ttk.Label(controls, text='Report:').grid(row=0, column=0, padx=(8, 4), pady=8, sticky='w')
        self.report_var = tk.StringVar(value='Policy Inventory')
        self.report_choices = {
            'Policy Inventory': 'policy-inventory',
            'Effective Permissions': 'permissions',
            'Policy Supersession': 'supersession',
            'Full Policy Overlaps': 'full-overlaps',
        }
        ttk.Combobox(
            controls, textvariable=self.report_var, values=list(self.report_choices), state='readonly', width=28
        ).grid(row=0, column=1, padx=4, pady=8, sticky='w')
        self.run_button = ttk.Button(controls, text='Run Report', command=self.run_selected_report)
        self.run_button.grid(row=0, column=2, padx=(12, 4), pady=8, sticky='w')
        ttk.Label(controls, text='Format:').grid(row=0, column=3, padx=(12, 4), pady=8, sticky='w')
        self.format_var = tk.StringVar(value='JSON')
        self.format_combo = ttk.Combobox(
            controls,
            textvariable=self.format_var,
            values=['JSON', 'Markdown', 'Rendered HTML'],
            state='readonly',
            width=16,
        )
        self.format_combo.grid(row=0, column=4, padx=4, pady=8, sticky='w')
        self.format_combo.bind('<<ComboboxSelected>>', lambda _event: self._refresh_preview())
        self.export_button = ttk.Button(controls, text='Export', command=self.export_report, state=tk.DISABLED)
        self.export_button.grid(row=0, column=5, padx=8, pady=8, sticky='w')
        self.status_var = tk.StringVar(value='Load policy data, then run a report.')
        ttk.Label(controls, textvariable=self.status_var).grid(row=0, column=6, padx=(12, 8), pady=8, sticky='w')

        preview = ttk.LabelFrame(self, text='Report Preview')
        preview.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        self.text_preview_frame = ttk.Frame(preview)
        self.preview = tk.Text(self.text_preview_frame, wrap=tk.WORD, state=tk.DISABLED, height=20)
        self.preview.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(self.text_preview_frame, orient='vertical', command=self.preview.yview)
        scrollbar.pack(side='right', fill='y')
        self.preview.configure(yscrollcommand=scrollbar.set)
        self.html_preview = HTMLText(
            preview,
            wrap=tk.WORD,
            state=tk.DISABLED,
        )

    def _service(self) -> ReportsService:
        """Return the shared-context report service."""
        return ReportsService(self.app.app_context)

    def run_selected_report(self) -> None:
        """Generate the selected report on demand."""
        self.status_var.set('Generating report…')
        self.update_idletasks()
        try:
            self._report = self._service().get_report(self.report_choices[self.report_var.get()])
        except Exception as exc:
            self.status_var.set('Report failed.')
            tkinter.messagebox.showerror('Report', str(exc))
            return
        self.export_button.configure(state=tk.NORMAL)
        self.status_var.set(self._completion_message())
        self._refresh_preview()

    def _completion_message(self) -> str:
        """Return a concise completion label appropriate to the generated report."""
        if not self._report:
            return 'Report complete.'
        if self._report.get('report_id') == 'policy-inventory':
            counts = self._report.get('counts') or {}
            return (
                'Report complete: '
                f'{counts.get("compartments", 0)} compartments, '
                f'{counts.get("policies", 0)} policies, '
                f'{counts.get("statements", 0)} statements.'
            )
        return (
            f'Report complete: {self._report.get("item_count", self._report.get("finding_count", 0))} '
            f'{self._report.get("item_label", "items").casefold()}.'
        )

    def _refresh_preview(self) -> None:
        """Display the generated report using the selected serialization."""
        if not self._report:
            return
        if self.format_var.get() == 'Rendered HTML':
            self.text_preview_frame.pack_forget()
            self.html_preview.pack(fill='both', expand=True, padx=6, pady=6)
            self.html_preview.configure(state=tk.NORMAL)
            self.html_preview.set_html(self._rendered_html())
            self.html_preview.configure(state=tk.DISABLED)
            return
        self.html_preview.pack_forget()
        self.text_preview_frame.pack(fill='both', expand=True, padx=6, pady=6)
        content = (
            json.dumps(self._report, indent=2, default=str)
            if self.format_var.get() == 'JSON'
            else self._service().to_markdown(self._report)
        )
        self.preview.configure(state=tk.NORMAL)
        self.preview.delete('1.0', tk.END)
        self.preview.insert('1.0', content)
        self.preview.configure(state=tk.DISABLED)

    def export_report(self) -> None:
        """Save the most recently generated report in the selected format."""
        if not self._report:
            return
        selected_format = self.format_var.get()
        markdown = selected_format == 'Markdown'
        rendered_html = selected_format == 'Rendered HTML'
        report_id = self._report.get('report_id') or 'report'
        path = tkfiledialog.asksaveasfilename(
            defaultextension='.html' if rendered_html else '.md' if markdown else '.json',
            initialfile=f'{report_id}-report.' + ('html' if rendered_html else 'md' if markdown else 'json'),
            filetypes=(
                [('HTML Files', '*.html')]
                if rendered_html
                else [('Markdown Files', '*.md')]
                if markdown
                else [('JSON Files', '*.json')]
            ),
        )
        if not path:
            return
        with open(path, 'w', encoding='utf-8') as stream:
            stream.write(
                self._html_document()
                if rendered_html
                else self._service().to_markdown(self._report)
                if markdown
                else json.dumps(self._report, indent=2, default=str)
            )
        self.status_var.set(f'Report exported: {path}')

    def _html_document(self) -> str:
        """Wrap safe report HTML in a portable, readable document."""
        body = self._rendered_html()
        return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>OCI Policy Analysis Report</title>
<style>body {{ font-family: Arial, sans-serif; line-height: 1.45; margin: 24px; color: #1f2937; }} h1, h2, h3 {{ color: #0f3d63; }} code {{ white-space: pre-wrap; overflow-wrap: anywhere; background: #f3f4f6; padding: 2px 4px; }} table {{ border-collapse: collapse; }} th, td {{ border: 1px solid #d1d5db; padding: 6px; }}</style>
</head><body>{body}</body></html>"""

    def _rendered_html(self) -> str:
        """Return safe HTML generated from the report Markdown."""
        return self._service().with_rendered_formats(self._report or {})['markdown_html']

    def populate_data(self) -> None:
        """Reset transient report results after loading another dataset."""
        self._report = None
        self.export_button.configure(state=tk.DISABLED)
        self.status_var.set('Policy data loaded. Run a report when needed.')
