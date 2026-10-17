"""Clearly labeled destinations for workflows awaiting their own Qt pages."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPushButton, QTabWidget, QVBoxLayout, QWidget

from oci_policy_analysis.presentation.qt.pages.condition_tester import ConditionTesterPage
from oci_policy_analysis.presentation.qt.pages.reports import ReportsPage
from oci_policy_analysis.presentation.qt.widgets import label


class PlannedWorkflowPage(QWidget):
    """Explain a planned workflow without presenting inactive controls as usable.

    Args:
        title: Workflow title.
        description: Purpose and planned interaction.
    """

    def __init__(self, title: str, description: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label(title, 'eyebrow'))
        layout.addWidget(label(description, wrap=True))
        layout.addWidget(
            label('Planned Qt workflow · No operation is performed on this page yet.', 'notice', wrap=True)
        )
        layout.addStretch()


class ToolsPage(QTabWidget):
    """Group utility destinations in native tabs; reuse existing logging controls.

    Args:
        experience: Shared mode policy controlling advanced-only Maintenance.

    Attributes:
        show_logs: Request the shell's existing log dock.
        show_logging_settings: Request the existing Overview logging settings.
    """

    show_logs = Signal()
    show_logging_settings = Signal()

    def __init__(self, experience) -> None:
        super().__init__()
        self.condition_tester = ConditionTesterPage()
        self.addTab(self.condition_tester, 'Condition Tester')
        self.reports = ReportsPage()
        self.addTab(self.reports, 'Reports')
        self.addTab(
            PlannedWorkflowPage(
                'Maintenance', 'Advanced cache and workbench maintenance. Explicit actions will be added here.'
            ),
            'Maintenance',
        )
        experience.bind_advanced_tab(self, 2)
        logging = QWidget()
        layout = QVBoxLayout(logging)
        layout.addWidget(label('Use the same live log and settings available on Overview.', wrap=True))
        button = QPushButton('Show live log')
        button.clicked.connect(self.show_logs.emit)
        layout.addWidget(button)
        button = QPushButton('Open logging settings')
        button.clicked.connect(self.show_logging_settings.emit)
        layout.addWidget(button)
        layout.addStretch()
        self.addTab(logging, 'Logging')
