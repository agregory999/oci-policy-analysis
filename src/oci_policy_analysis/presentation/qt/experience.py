"""One shared presentation-mode switch for navigation and individual widgets."""

from PySide6.QtCore import QObject, Signal

from oci_policy_analysis.presentation.qt.preferences import save_preferences


class ExperienceMode(QObject):
    """Publish and persist the Qt experience without changing analysis behavior.

    Args:
        settings: Shared session preferences; only qt_advanced_mode is persisted.
        parent: Owner of this window's mode state.

    Attributes:
        advanced: Whether advanced workflows and controls are visible.
        changed: Emitted once when the effective mode changes.
        status: Persistence feedback for the settings panel.

    Notes:
        This is a presentation preference, not an authorization boundary. It
        never loads data, starts a workflow, or discards hidden widget state.
    """

    changed = Signal(bool)
    status = Signal(str)

    def __init__(self, settings: dict, parent: QObject) -> None:
        super().__init__(parent)
        self.settings = settings
        self.advanced = settings.get('qt_advanced_mode') is True

    def set_advanced(self, advanced: bool) -> None:
        """Update every subscribed control and save the preference if possible."""
        if self.advanced == advanced:
            return
        self.advanced = advanced
        self.settings['qt_advanced_mode'] = advanced
        self.changed.emit(advanced)
        try:
            save_preferences(self.settings, ('qt_advanced_mode',))
            self.status.emit('Advanced mode saved.' if advanced else 'Standard mode saved.')
        except OSError:
            self.status.emit('Mode changed for this session; the preference could not be saved.')

    def bind_advanced(self, widget) -> None:
        """Show a window-owned widget only in advanced mode, now and on changes."""
        widget.setVisible(self.advanced)
        self.changed.connect(widget.setVisible)

    def bind_advanced_tab(self, tabs, index: int) -> None:
        """Apply the same advanced-mode policy to a native QTabWidget tab."""
        tabs.setTabVisible(index, self.advanced)
        self.changed.connect(lambda advanced: tabs.setTabVisible(index, advanced))
