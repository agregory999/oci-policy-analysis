"""Interactive condition parsing and testing using the shared evaluator."""

import json
from dataclasses import asdict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.application.services.condition_tester_service import ConditionTesterService
from oci_policy_analysis.presentation.qt.tables import RecordTable
from oci_policy_analysis.presentation.qt.widgets import label


class ConditionTesterPage(QWidget):
    """Parse a clause, collect simulated values and inspect individual comparisons.

    Attributes:
        clause: Editable condition or full-policy input.
        input_widgets: Variable-name mapping to text inputs and null toggles.
        structure: Read-only JSON representation of parsed logic and atoms.
        comparisons: Evaluation log table; original logs remain in raw_result.

    Notes:
        Uses ConditionTesterService exclusively for parsing and evaluation.
        Runs without tenancy data and does not save test cases to settings or caches.
        Edits invalidate results until the current clause is parsed again.
    """

    def __init__(self):
        """Build a standalone tester with resizable inputs, structure and results."""
        super().__init__()
        self.service = ConditionTesterService()
        self.input_widgets = {}
        self.parsed = None
        self._parsed_source = ''
        layout = QVBoxLayout(self)
        layout.addWidget(
            label(
                'Test a condition using simulated values. This does not determine OCI access. Blank inputs mean null / not supplied; !variable matches when no value is supplied.',
                'notice',
                wrap=True,
            )
        )
        self.clause = QPlainTextEdit()
        self.clause.setPlaceholderText(
            'Enter a condition, where clause, or full policy. Example: all { request.principal.id = target.bucket.owner.id, !request.principal.type }'
        )
        self.clause.setMaximumHeight(130)
        layout.addWidget(self.clause)
        actions = QHBoxLayout()
        self.parse_button = QPushButton('Parse and generate inputs')
        self.parse_button.setObjectName('primary')
        self.parse_button.clicked.connect(self.parse_clause)
        actions.addWidget(self.parse_button)
        format_button = QPushButton('Format')
        format_button.clicked.connect(self._format)
        actions.addWidget(format_button)
        self.evaluate_button = QPushButton('Test condition')
        self.evaluate_button.setEnabled(False)
        self.evaluate_button.clicked.connect(self.evaluate)
        actions.addWidget(self.evaluate_button)
        clear = QPushButton('Clear')
        clear.clicked.connect(self._clear)
        actions.addWidget(clear)
        actions.addStretch()
        layout.addLayout(actions)
        self.status = label('Enter a condition to begin.', 'muted', wrap=True)
        layout.addWidget(self.status)
        vertical = QSplitter(Qt.Orientation.Vertical)
        upper = QSplitter(Qt.Orientation.Horizontal)
        self.inputs = QScrollArea()
        self.inputs.setWidgetResizable(True)
        upper.addWidget(self.inputs)
        self.structure = QPlainTextEdit()
        self.structure.setReadOnly(True)
        self.structure.setPlaceholderText('Parsed structure and diagnostics appear here as JSON.')
        upper.addWidget(self.structure)
        upper.setSizes([600, 450])
        vertical.addWidget(upper)
        output = QWidget()
        output_layout = QVBoxLayout(output)
        output_layout.setContentsMargins(0, 4, 0, 0)
        self.result = label('No test run.', 'eyebrow', wrap=True)
        output_layout.addWidget(self.result)
        tabs = QTabWidget()
        self.comparisons = RecordTable(
            (
                ('Result', 'outcome'),
                ('Variable', 'variable'),
                ('Operator', 'operator'),
                ('Input', 'sim_value'),
                ('Expected', 'expected'),
                ('Comparison', 'type'),
                ('Details', 'info'),
            )
        )
        self.comparisons.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.comparisons.setColumnWidth(0, 75)
        self.comparisons.setColumnWidth(1, 220)
        self.comparisons.setColumnWidth(2, 75)
        tabs.addTab(self.comparisons, 'Comparisons')
        self.raw_result = QPlainTextEdit()
        self.raw_result.setReadOnly(True)
        tabs.addTab(self.raw_result, 'Result JSON')
        output_layout.addWidget(tabs)
        vertical.addWidget(output)
        vertical.setSizes([300, 220])
        layout.addWidget(vertical, 1)
        self.clause.textChanged.connect(self._invalidate_clause)
        self._replace_inputs([])

    def set_clause_text(self, text: str) -> None:
        """Load a handoff into the tester and parse without evaluating it.

        Args:
            text: Condition or complete statement selected in another view.

        Notes:
            Clears prior simulated inputs to prevent values leaking between cases.
        """
        self._replace_inputs([])
        self.clause.setPlainText(text)
        self.parse_clause()

    def _invalidate_result(self, *_args):
        self.result.setText('Inputs changed · Test again.' if self.parsed else 'No test run.')
        self.comparisons.model.replace([])
        self.raw_result.clear()

    def _invalidate_clause(self):
        self.parsed = None
        self.evaluate_button.setEnabled(False)
        self.structure.clear()
        self.inputs.setEnabled(False)
        self.status.setText('Clause changed · Parse to update the structure and inputs.')
        self._invalidate_result()

    def _replace_inputs(self, names, prior=None):
        content = QWidget()
        form = QFormLayout(content)
        self.input_widgets = {}
        if not names:
            form.addRow(label('Parse a condition to generate inputs for its variables.', 'muted', wrap=True))
        for name in names:
            value = QLineEdit()
            value.setPlaceholderText(
                {'request.utc-timestamp': '2026-01-05T12:34:56Z', 'request.utc-timestamp.time-of-day': '13:27:00Z'}.get(
                    name, 'Blank = null / not supplied'
                )
            )
            null = QCheckBox('Null / not supplied')
            if prior and name in prior:
                value.setText(prior[name][0])
                null.setChecked(prior[name][1])
            value.setEnabled(not null.isChecked())
            null.toggled.connect(value.setDisabled)
            null.toggled.connect(self._invalidate_result)
            value.textChanged.connect(self._invalidate_result)
            row = QHBoxLayout()
            row.addWidget(value, 1)
            row.addWidget(null)
            form.addRow(name, row)
            self.input_widgets[name] = (value, null)
        old = self.inputs.takeWidget()
        self.inputs.setWidget(content)
        if old:
            old.deleteLater()

    def parse_clause(self) -> None:
        """Parse the current text, expose diagnostics and generate both operand fields."""
        prior = {name: (value.text(), null.isChecked()) for name, (value, null) in self.input_widgets.items()}
        self._invalidate_result()
        self.result.setText('No test run.')
        self.parsed = None
        try:
            parsed = self.service.parse_clause(self.clause.toPlainText())
            self.structure.setPlainText(json.dumps(parsed, indent=2, ensure_ascii=False))
            valid = parsed['structure']['parse_status'] == 'parsed'
            self._replace_inputs(parsed['variables'], prior)
            self.inputs.setEnabled(valid)
            self.evaluate_button.setEnabled(valid)
            if valid:
                self.parsed = parsed
                self._parsed_source = self.clause.toPlainText()
                self.status.setText(
                    f'Parsed · {len(parsed["variables"])} variables · {len(parsed["structure"]["atoms"])} predicates. Supply values, then test.'
                )
            else:
                diagnostics = '; '.join(parsed['structure']['warnings']) or 'No condition expression found.'
                self.status.setText('Cannot test: ' + diagnostics)
        except Exception as exc:
            self.evaluate_button.setEnabled(False)
            self.status.setText(f'Could not parse condition: {exc}')

    def evaluate(self) -> None:
        """Evaluate only the current parsed expression and show full comparison evidence."""
        if not self.parsed or self._parsed_source != self.clause.toPlainText():
            return
        variables = {
            name: None if null.isChecked() or value.text() == '' else value.text()
            for name, (value, null) in self.input_widgets.items()
        }
        try:
            evaluated = self.service.evaluate(self.parsed['clause'], variables)
            errors = [entry for entry in evaluated.log if entry.get('type') == 'Exception']
            self.result.setText(
                'Evaluation error · See comparison details.'
                if errors
                else ('Condition matched' if evaluated.granted else 'Condition did not match')
            )
            self.comparisons.model.replace(
                [{**entry, 'outcome': 'PASS' if entry.get('result') else 'FAIL'} for entry in evaluated.log]
            )
            self.raw_result.setPlainText(
                json.dumps({'inputs': variables, **asdict(evaluated)}, indent=2, ensure_ascii=False, default=str)
            )
        except Exception as exc:
            self._invalidate_result()
            self.result.setText(f'Could not test condition: {exc}')

    def _format(self):
        parsed = self.service.parse_clause(self.clause.toPlainText())
        if parsed['structure']['parse_status'] != 'parsed':
            self.parse_clause()
            return
        self.clause.setPlainText(self.service.format_clause(parsed['clause']))
        self.parse_clause()

    def _clear(self):
        self.clause.clear()
        self._replace_inputs([])
        self.structure.clear()
        self.status.setText('Enter a condition to begin.')
