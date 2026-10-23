"""Shared light/dark colors for Qt widgets, popups, and native graph items."""

import re

from PySide6.QtGui import QColor, QFontDatabase, QFontInfo, QPalette
from PySide6.QtWidgets import QApplication

from oci_policy_analysis.presentation.qt.widgets import STYLE

DARK_COLORS = {
    '#243d39': '#e0e9e5',
    '#f5f6f2': '#17221f',
    '#163e38': '#102b25',
    '#c3d8d1': '#c3d8d1',
    '#53726a': '#a6c4b7',
    '#62766f': '#afc3b9',
    '#eeeade': '#363c2b',
    '#63583b': '#e2d8b4',
    '#dde4dd': '#40554c',
    '#c9d4cd': '#496257',
    '#e9efea': '#354a40',
    '#85958c': '#8fa497',
    '#e9ede8': '#293a32',
    '#d9eae0': '#3b6553',
    '#edf1eb': '#2e4036',
    '#dfe8df': '#364a3f',
    '#eaf0e8': '#22362b',
    '#bdcec3': '#496257',
    '#d8ebe1': '#294c40',
    '#e9eee5': '#354a40',
    '#f0e9db': '#51472f',
    '#e7ecdf': '#354a40',
    '#f0dfd8': '#573b32',
    '#f4edda': '#51472f',
    '#a9bfb5': '#668b78',
    '#6c9584': '#8bb49f',
}


COLOR_THEMES = {'Forest': None, 'Ocean': 212, 'Plum': 280, 'Slate': 210}


def _colorize(color: str, color_theme: str) -> str:
    hue = COLOR_THEMES.get(color_theme)
    if hue is None or color == '#363c2b':
        return color
    value = QColor(color)
    original_hue, saturation, lightness, alpha = value.getHslF()
    # Tint the green visual system; retain warning/grant/deny semantic colors.
    if 70 <= original_hue * 360 <= 185 and saturation > 0.01:
        value.setHslF(hue / 360, saturation * (0.15 if color_theme == 'Slate' else 1), lightness, alpha)
        return value.name()
    return color


def theme_color(color: str, theme: str, color_theme: str = 'Forest') -> str:
    """Resolve a semantic light color for the appearance and color palette.

    Args:
        color: Original light-theme CSS color.
        theme: Light or Dark preference.
        color_theme: Named palette for the app surfaces and accent colors.

    Returns:
        str: Theme-aware CSS color, retaining unknown values.
    """
    return _colorize(DARK_COLORS.get(color, color) if theme == 'Dark' else color, color_theme)


def apply_theme(theme: str, size: int, color_theme: str = 'Forest') -> str:
    """Apply a Fusion palette and return the matching window stylesheet.

    Args:
        theme: Light or Dark preference.
        size: Base font size in pixels.
        color_theme: Forest, Ocean, Plum, or Slate palette.

    Returns:
        str: Complete stylesheet covering widgets, menus, tabs and scroll areas.
    """
    application = QApplication.instance()
    palette = application.style().standardPalette()
    dark = theme == 'Dark'
    roles = {
        QPalette.ColorRole.Window: '#17221f' if dark else '#f5f6f2',
        QPalette.ColorRole.Base: '#22322a' if dark else '#ffffff',
        QPalette.ColorRole.AlternateBase: '#2e4036' if dark else '#edf1eb',
        QPalette.ColorRole.Text: '#e0e9e5' if dark else '#243d39',
        QPalette.ColorRole.WindowText: '#e0e9e5' if dark else '#243d39',
        QPalette.ColorRole.Button: '#293e33' if dark else '#ffffff',
        QPalette.ColorRole.ButtonText: '#e0e9e5' if dark else '#243d39',
        QPalette.ColorRole.ToolTipBase: '#293e33' if dark else '#ffffff',
        QPalette.ColorRole.ToolTipText: '#e0e9e5' if dark else '#243d39',
        QPalette.ColorRole.Highlight: '#3b6553' if dark else '#d9eae0',
        QPalette.ColorRole.HighlightedText: '#ffffff' if dark else '#163e38',
        QPalette.ColorRole.PlaceholderText: '#9bb2a6' if dark else '#62766f',
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(_colorize(color, color_theme)))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor('#85958c'))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor('#85958c'))
    application.setPalette(palette)
    extra = """
QPushButton#primary:disabled { background: #e9ede8; border-color: #c9d4cd; color: #85958c; }
QSpinBox QLineEdit { padding: 0px; border: none; background: transparent; }
QWidget#detailsDrawer { background: white; border: 1px solid #bdcec3; border-radius: 8px; }
QToolButton#sectionHeader { text-align: left; padding: 10px; font-weight: 600; background: white; border: 1px solid #c9d4cd; border-radius: 5px; }
QToolButton#multiSelectFilter { padding: 8px 22px 8px 10px; background: white; border: 1px solid #c9d4cd; border-radius: 4px; }
QToolButton#segment { background: white; border: 1px solid #c9d4cd; padding: 7px 12px; }
QToolButton#segment:checked { background: #1e6554; color: #ffffff; }
QPushButton#navigationLog { background: #2b554d; color: #ffffff; border-color: #53726a; text-align: left; }
QPushButton#navigationLog:hover { background: #287962; }
QScrollArea, QScrollArea > QWidget > QWidget { background: #f5f6f2; }
QMenu, QComboBox QAbstractItemView { background: white; color: #243d39; border: 1px solid #c9d4cd; }
QMenu::item { padding: 7px 18px; }
QMenu::item:selected { background: #d9eae0; }
QTabWidget::pane { border: 1px solid #c9d4cd; }
QTabBar::tab { background: #edf1eb; padding: 8px 14px; }
QTabBar::tab:selected { background: white; }
QLabel#metric { font-size: 21px; }
QLabel#metricTitle { font-size: 11px; color: #62766f; }
QComboBox#logLevel { padding: 3px 6px; min-width: 90px; }
QFrame#separator { color: #c9d4cd; }
"""
    style = re.sub(
        r'font-size: (\d+)px', lambda match: f'font-size: {round(int(match[1]) * size / 13)}px', STYLE + extra
    )
    if dark:
        style = re.sub(r'#[0-9a-fA-F]{6}\b', lambda match: DARK_COLORS.get(match[0], match[0]), style)
        style = style.replace('background: white', 'background: #22322a')
        style += '\nQTableView, QPlainTextEdit { selection-color: #ffffff; }'
    return re.sub(r'#[0-9a-fA-F]{6}\b', lambda match: _colorize(match[0], color_theme), style)


def fixed_width_family() -> str:
    """Return an installed fixed-pitch font, including platform-specific fallbacks.

    Returns:
        str: Resolved system font family; generic aliases are replaced when Qt's
        offscreen/native platform cannot resolve them to an actual fixed font.
    """
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    info = QFontInfo(font)
    if info.fixedPitch():
        return info.family()
    families = QFontDatabase.families()
    for family in ['Menlo', 'Consolas', 'DejaVu Sans Mono', 'Liberation Mono', *families]:
        if family in families and QFontDatabase.isFixedPitch(family):
            return family
    return info.family()
