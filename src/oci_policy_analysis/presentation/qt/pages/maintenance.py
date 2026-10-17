"""Explicit saved-cache maintenance using the shared cache service."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget

from oci_policy_analysis.application.services.cache_service import CacheService
from oci_policy_analysis.presentation.qt.tables import RecordTable
from oci_policy_analysis.presentation.qt.widgets import label


class MaintenancePage(QWidget):
    """Rename, lock and delete saved caches without changing loaded data.

    Args:
        cache: Shared cache manager for the operator's selected cache directory.

    Attributes:
        changed: Emitted after a successful mutation with action and cache names.
    """

    changed = Signal(object)

    def __init__(self, cache) -> None:
        super().__init__()
        self.service = CacheService(cache)
        self.block_reason = ''
        layout = QVBoxLayout(self)
        layout.addWidget(label('Saved caches', 'eyebrow'))
        layout.addWidget(
            label(
                'Locked caches are kept by automatic cleanup and must be unlocked before deletion. '
                'Renaming retains snapshot contents and the lock. Loaded data stays in memory.',
                wrap=True,
            )
        )
        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search saved caches')
        controls.addWidget(self.search, 1)
        self.refresh_button = QPushButton('Refresh')
        self.rename_button = QPushButton('Rename…')
        self.lock_button = QPushButton('Lock')
        self.delete_button = QPushButton('Delete…')
        for button in (self.refresh_button, self.rename_button, self.lock_button, self.delete_button):
            controls.addWidget(button)
        layout.addLayout(controls)
        self.table = RecordTable((('Locked', 'locked'), ('Cache name', 'name')))
        layout.addWidget(self.table, 1)
        self.status = label('', wrap=True)
        layout.addWidget(self.status)
        self.search.textChanged.connect(self.table.proxy.setFilterFixedString)
        self.table.selectionModel().selectionChanged.connect(self._controls)
        self.refresh_button.clicked.connect(self.refresh_caches)
        self.rename_button.clicked.connect(self._rename)
        self.lock_button.clicked.connect(self._lock)
        self.delete_button.clicked.connect(self._delete)
        self.refresh_caches()

    def refresh_caches(self) -> None:
        """Refresh index metadata without loading any snapshot into the application."""
        try:
            self.table.model.replace(self.service.maintenance_records())
        except OSError as exc:
            self.table.model.replace([])
            self.status.setText(f'Could not list caches: {exc}')
        self._controls()

    def set_block_reason(self, reason: str) -> None:
        """Prevent mutations while a snapshot-dependent task is active."""
        self.block_reason = reason
        self._controls()

    def _selected(self):
        rows = self.table.selected_records()
        return rows[0] if rows else None

    def _controls(self, *_args):
        row = self._selected()
        available = bool(row) and not self.block_reason
        self.rename_button.setEnabled(available)
        self.lock_button.setEnabled(available)
        self.delete_button.setEnabled(available and not row['locked'])
        self.lock_button.setText('Unlock' if row and row['locked'] else 'Lock')
        for button in (self.rename_button, self.lock_button, self.delete_button):
            button.setToolTip(self.block_reason)

    def _finish(self, success, action, row, new_name=None):
        if not success:
            self.status.setText('Cache operation failed. Refresh and check the name, lock, permissions and live log.')
            return
        self.refresh_caches()
        self.status.setText(f'{action}: {new_name or row["name"]}')
        self.changed.emit({'action': action, 'old_name': row['name'], 'new_name': new_name})

    def _rename(self):
        row = self._selected()
        if not row or self.block_reason:
            return
        name, accepted = QInputDialog.getText(
            self,
            'Rename saved cache',
            'Cache name (tenancy_label; no path or Windows-invalid characters):',
            text=row['name'],
        )
        if accepted and name != row['name']:
            self._finish(self.service.rename_cache(row['name'], name), 'Renamed', row, name)

    def _lock(self):
        row = self._selected()
        if row and not self.block_reason:
            locked = not row['locked']
            self._finish(self.service.set_locked(row['name'], locked), 'Locked' if locked else 'Unlocked', row)

    def _delete(self):
        row = self._selected()
        if not row or row['locked'] or self.block_reason:
            return
        answer = QMessageBox.question(
            self,
            'Delete saved cache',
            f'Permanently delete this saved cache?\n\n{row["name"]}\n\nThis cannot be undone.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._finish(self.service.remove_cache(row['name']), 'Deleted', row)
