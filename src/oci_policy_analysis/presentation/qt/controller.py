"""Own the current context and publish successful asynchronous loads to pages."""

import copy

from PySide6.QtCore import QObject, Signal, Slot

from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.presentation.qt.loading import LoadWorker

logger = get_logger(component='qt.main')


class WorkbenchController(QObject):
    """Coordinate load lifecycle independently of navigation and page widgets.

    Attributes:
        context: Latest successful context; None until the first successful load.
        settings: Session settings copied into each candidate context.
        worker: Active load thread, or None. Never read its context while loading.
    """

    progress = Signal(str, str, str)
    loaded = Signal(object, object, str)
    failed = Signal(str)
    busy_changed = Signal(bool)
    activity = Signal(str)

    def __init__(self, settings: dict, parent: QObject) -> None:
        """Retain session settings without constructing a context or accessing OCI."""
        super().__init__(parent)
        self.context = None
        self.settings = settings
        self.worker = None
        self._description = ''
        self.load_block_reason = ''

    @Slot(str, dict, str)
    def start_load(self, source: str, options: dict, description: str) -> None:
        """Start one worker, preserving the published context until success."""
        if self.load_block_reason:
            logger.warning('Load blocked: %s', self.load_block_reason)
            self.activity.emit(self.load_block_reason)
            return
        if self.worker is not None:
            logger.warning('Ignored concurrent load request')
            return
        self._description = description
        self.activity.emit(f'\nStarting {description}')
        logger.info('Starting load: source=%s', source)
        self.worker = LoadWorker(source, options, copy.deepcopy(self.settings), self)
        self.worker.progress.connect(self._on_progress)
        self.worker.loaded.connect(self._on_loaded)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._on_finished)
        self.busy_changed.emit(True)
        self.worker.start()

    @Slot(str, str, str)
    def _on_progress(self, stage: str, detail: str, state: str) -> None:
        self.activity.emit(f'{stage}: {detail}')
        self.progress.emit(stage, detail, state)
        logger.info('%s · %s', stage, detail)

    @Slot(object, object)
    def _on_loaded(self, context, result) -> None:
        self.context = context
        self.loaded.emit(context, result, self._description)
        warnings = getattr(context.policy_repo, '_cleanup_reload_api_errors', []) or []
        if warnings:
            self.activity.emit(
                f'Collection findings: {len(warnings)} failed operations. See Logs → API Calls for response codes, reasons, timings, and request IDs. These diagnostics are retained only in memory.'
            )
        self.activity.emit('Snapshot published. Source files were not rewritten.')
        logger.info('Published snapshot: %s', result.summary)

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        logger.error('Load failed; previous snapshot retained: %s', message)
        self.activity.emit(f'Load failed: {message}\nPrevious snapshot retained.')
        self.failed.emit(message)

    @Slot()
    def _on_finished(self) -> None:
        worker = self.worker
        self.worker = None
        if worker:
            worker.deleteLater()
        self.busy_changed.emit(False)
