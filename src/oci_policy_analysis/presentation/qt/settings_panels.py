"""Focused Qt settings widgets using the desktop/web setting names."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.application.core.engine.intelligence_strategies import get_default_intelligence_strategies
from oci_policy_analysis.presentation.qt.preferences import save_preferences
from oci_policy_analysis.presentation.qt.themes import COLOR_THEMES
from oci_policy_analysis.presentation.qt.widgets import label


class IntelligencePanel(QWidget):
    """Configure enrichment and registered strategy selection for the next load."""

    def __init__(self, settings: dict) -> None:
        """Use the same strategy registry and risk defaults as desktop/web settings."""
        super().__init__()
        self.settings = settings
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        self.profile = QComboBox()
        self.profile.addItem('Query foundations', 'minimal')
        self.profile.addItem('Full intelligence', 'full')
        self.profile.setCurrentIndex(max(0, self.profile.findData(settings.get('qt_post_load_profile', 'minimal'))))
        form.addRow('After loading', self.profile)
        self.where_reduction = QComboBox()
        self.service_reduction = QComboBox()
        for combo, key in [
            (self.where_reduction, 'risk_where_clause_reduction_pct'),
            (self.service_reduction, 'risk_service_principal_reduction_pct'),
        ]:
            combo.addItems(['0%', '25%', '50%', '75%', '90%'])
            combo.setCurrentText(f'{settings.get(key, 50)}%')
        form.addRow('WHERE risk reduction', self.where_reduction)
        form.addRow('Service principal risk reduction', self.service_reduction)
        layout.addLayout(form)
        grid = QGridLayout()
        self.strategy_grid = grid
        self.strategy_columns = 2
        self.strategies = {}
        saved = settings.get('enabled_intelligence_checks') or []
        for index, strategy in enumerate(get_default_intelligence_strategies()):
            check = QCheckBox(strategy.display_name)
            check.setChecked(not saved or strategy.strategy_id in saved)
            self.strategies[strategy.strategy_id] = check
            grid.addWidget(check, index // 2, index % 2)
        layout.addLayout(grid)
        button = QPushButton('Apply to next load')
        button.clicked.connect(self.apply_settings)
        layout.addWidget(button)
        self.status = label('Strategies and risk settings run with Full intelligence.', 'muted', wrap=True)
        layout.addWidget(self.status)

    def reflow_columns(self, available: int) -> None:
        """Use one strategy column when large text exceeds the available width.

        Args:
            available: Width of the containing Overview viewport in pixels.
        """
        required = 2 * max(check.sizeHint().width() for check in self.strategies.values()) + 30
        columns = 1 if required > available else 2
        if columns == self.strategy_columns:
            return
        self.strategy_columns = columns
        for index, check in enumerate(self.strategies.values()):
            self.strategy_grid.removeWidget(check)
            self.strategy_grid.addWidget(check, index // columns, index % columns)

    def apply_settings(self) -> None:
        """Store session settings without mutating the currently displayed context."""
        enabled = [key for key, check in self.strategies.items() if check.isChecked()]
        if not enabled:
            self.status.setText('Select at least one strategy. Use Query foundations to skip the full run.')
            return
        self.settings.update(
            {
                'qt_post_load_profile': self.profile.currentData(),
                'enabled_intelligence_checks': enabled if len(enabled) < len(self.strategies) else [],
                'risk_where_clause_reduction_pct': int(self.where_reduction.currentText().rstrip('%')),
                'risk_service_principal_reduction_pct': int(self.service_reduction.currentText().rstrip('%')),
            }
        )
        self.status.setText('Applied to the next load. Current results are unchanged.')


class AppearancePanel(QWidget):
    """Apply text sizing and table density without rebuilding or reloading data."""

    changed = Signal(dict)

    def __init__(self, settings: dict) -> None:
        """Build the current session appearance controls."""
        super().__init__()
        self.settings = settings
        layout = QFormLayout(self)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.theme = QComboBox()
        self.theme.addItems(['Light', 'Dark'])
        self.theme.setCurrentText(settings.get('qt_theme', 'Light'))
        self.theme.setMinimumWidth(175)
        layout.addRow('Appearance', self.theme)
        self.color_theme = QComboBox()
        self.color_theme.addItems(list(COLOR_THEMES))
        self.color_theme.setCurrentText(settings.get('qt_color_theme', 'Forest'))
        self.color_theme.setMinimumWidth(175)
        layout.addRow('Color theme', self.color_theme)
        self.font_size = QComboBox()
        self.font_size.addItems(['Small', 'Medium', 'Large', 'Extra Large'])
        self.font_size.setCurrentText(settings.get('font_size', 'Medium'))
        self.font_size.setMinimumWidth(175)
        layout.addRow('Text size', self.font_size)
        self.fixed_width = QCheckBox('Fixed-width font for tables and Overview settings')
        self.fixed_width.setChecked(settings.get('qt_fixed_width_font', False))
        layout.addRow(self.fixed_width)
        self.compact = QCheckBox('Compact policy rows')
        self.compact.setChecked(settings.get('qt_compact_rows', False))
        layout.addRow(self.compact)
        button = QPushButton('Apply appearance')
        button.clicked.connect(self.apply_settings)
        layout.addRow(button)
        self.status = label('', 'muted', wrap=True)
        layout.addRow(self.status)

    def apply_settings(self) -> None:
        """Publish session appearance values to the window shell."""
        self.settings.update(
            {
                'qt_theme': self.theme.currentText(),
                'qt_color_theme': self.color_theme.currentText(),
                'font_size': self.font_size.currentText(),
                'qt_compact_rows': self.compact.isChecked(),
                'qt_fixed_width_font': self.fixed_width.isChecked(),
            }
        )
        self.changed.emit(dict(self.settings))
        try:
            save_preferences(
                self.settings, ('qt_theme', 'qt_color_theme', 'font_size', 'qt_compact_rows', 'qt_fixed_width_font')
            )
            self.status.setText('Appearance applied and saved.')
        except OSError as exc:
            self.status.setText(f'Applied for this session. {exc}')
