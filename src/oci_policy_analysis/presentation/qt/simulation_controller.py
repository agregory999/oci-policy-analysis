"""Own asynchronous statement preparation and snapshot-bound inclusion state."""

from PySide6.QtCore import QObject, QThread, Signal

from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.simulation_service import SimulationService
from oci_policy_analysis.application.services.simulation_workbench_service import SimulationWorkbenchService

logger = get_logger(component='qt.simulation')


class SimulationTaskWorker(QThread):
    """Own one serialized execution or suggestion request until completion.

    Args:
        context: Current snapshot held alive by this worker.
        action: execute or suggestions.
        payload: Detached request or candidate-generation arguments.
        revision: Snapshot/environment generation for rejecting obsolete results.
        parent: Owning workflow controller.
    """

    completed = Signal(int, str, object)
    failed = Signal(int, str)

    def __init__(self, context, action, payload, revision, parent):
        super().__init__(parent)
        from copy import deepcopy

        self.context, self.action = context, action
        self.payload, self.revision = deepcopy(payload), revision

    def run(self):
        """Execute against the active snapshot and report failures at INFO."""
        logger.info('Simulation task started: action=%s revision=%d', self.action, self.revision)
        try:
            service = SimulationWorkbenchService(self.context)
            if self.action == 'execute':
                report = service.execute(self.payload)
                result = {'report': report, 'history': service.history()}
            else:
                result = service.policy_candidates(**self.payload)
            logger.info('Simulation task completed: action=%s revision=%d', self.action, self.revision)
            self.completed.emit(self.revision, self.action, result)
        except Exception as exc:
            logger.info('Simulation task failed: action=%s reason=%s', self.action, exc, exc_info=True)
            self.failed.emit(self.revision, str(exc))


class StatementPreparationWorker(QThread):
    """Prepare candidates off the UI thread while the shell locks mutation.

    Args:
        context: Current context held alive for the duration of preparation.
        scenario: Copy of principal and compartment inputs.
        revision: Generation used to reject obsolete results.
        parent: Controller owning this thread until completion.
    """

    prepared = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, context, scenario, revision, parent):
        super().__init__(parent)
        self.context = context
        self.scenario = dict(scenario)
        self.revision = revision

    def run(self):
        """Discover candidates without evaluating a request or recording history."""
        logger.info('Preparing statement selection: revision=%d environment=%s', self.revision, self.scenario)
        try:
            service = SimulationService(self.context)
            result = service.statement_candidates(
                compartment_path=self.scenario['compartment_path'],
                principal_type=self.scenario['principal_type'],
                principal=self.scenario['principal'],
            )
            result['request_context_schema'] = service.request_context_schema(
                [row for row in result['statements'] if row['checkable']]
            )
            logger.info(
                'Statement selection prepared: revision=%d candidates=%d', self.revision, len(result['statements'])
            )
            self.prepared.emit(self.revision, result)
        except Exception as exc:
            logger.info(
                'Statement selection preparation failed: revision=%d reason=%s', self.revision, exc, exc_info=True
            )
            self.failed.emit(self.revision, str(exc))


class SimulationController(QObject):
    """Invalidate prepared evidence on upstream changes and reject late workers.

    Attributes:
        worker: Owned preparation thread or None; shutdown must await completion.
        checked_ids: Explicit inclusion list, including an intentional empty list.
        ready: Whether candidates belong to the current environment and snapshot.
        busy_changed: Shell lock for load, prospective editing and embedded MCP.
    """

    busy_changed = Signal(bool)
    prepared = Signal(object)
    invalidated = Signal()
    failed = Signal(str)
    executed = Signal(object, object)
    suggestions_ready = Signal(object)

    def __init__(self, parent):
        """Start with no context, environment or checked source IDs."""
        super().__init__(parent)
        self.context = None
        self.scenario = None
        self.worker = None
        self.revision = 0
        self.checked_ids = []
        self.ready = False
        self.block_reason = ''
        self.condition_schema = {'variables': [], 'conditions': []}
        self.api_operation = ''
        self.operation_name = ''
        self.where_values = {}
        self.last_report = None
        self.history = []

    def set_context(self, context):
        """Replace the snapshot and invalidate all prepared inclusion state.

        Args:
            context: Newly published AppContext; old workers cannot publish into it.
        """
        self.context = context
        self.last_report = None
        self.history = SimulationWorkbenchService(context).history()
        self.set_environment(None, force=True)

    def set_environment(self, scenario, *, force=False):
        """Clear downstream state when principal, compartment or prospects change.

        Args:
            scenario: Principal/type/path inputs, or None for an incomplete setup.
            force: Invalidate even with identical inputs after prospective changes.
        """
        if not force and self.scenario == scenario:
            return
        self.scenario = dict(scenario) if scenario else None
        self.revision += 1
        self.checked_ids = []
        self.condition_schema = {'variables': [], 'conditions': []}
        self.api_operation = ''
        self.operation_name = ''
        self.where_values = {}
        self.ready = False
        self.invalidated.emit()

    def prepare(self):
        """Start one worker after prerequisites and the shell lock are checked."""
        if self.worker is not None:
            return
        if self.block_reason:
            logger.info('Statement selection blocked: %s', self.block_reason)
            self.failed.emit(self.block_reason)
            return
        if self.context is None or self.scenario is None:
            self.failed.emit('Choose a principal and effective compartment on Environment first.')
            return
        if self.ready:
            self.prepared.emit(None)
            return
        self.worker = StatementPreparationWorker(self.context, self.scenario, self.revision, self)
        self.worker.prepared.connect(self._prepared)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._finished)
        self.busy_changed.emit(True)
        self.worker.start()

    def _prepared(self, revision, result):
        if revision != self.revision:
            logger.info('Discarded obsolete statement selection: revision=%d current=%d', revision, self.revision)
            return
        self.ready = True
        self.condition_schema = result['request_context_schema']
        self.checked_ids = [str(row['internal_id']) for row in result['statements'] if row['checkable']]
        self.prepared.emit(result)

    def request_payload(self) -> dict:
        """Return the current explicit request inputs without running a simulation.

        Returns:
            dict: Environment, checked IDs, canonical operation and supplied values.
                Blank/null values are omitted. request.operation is derived from
                reference metadata, matching the engine's execution behavior.
        """
        values = {name: value for name, value in self.where_values.items() if value is not None and value != ''}
        if self.api_operation:
            values['request.operation'] = self.operation_name
        return {
            **(self.scenario or {}),
            'checked_statement_ids': list(self.checked_ids),
            'api_operation': self.api_operation,
            'where_context': values,
        }

    def _failed(self, revision, message):
        if revision == self.revision:
            self.ready = False
            self.failed.emit(message)

    def execute(self):
        """Run the explicit current request; never substitute all statements for []."""
        if not self.ready or not self.api_operation:
            self.failed.emit('Prepare statements and choose an API operation before running.')
            return
        self._start_task('execute', self.request_payload())

    def suggest(self, report, options):
        """Generate reviewable candidates from one original result and user choices."""
        self._start_task('suggestions', {'report': report, **options})

    def _start_task(self, action, payload):
        if self.worker is not None:
            return
        if self.block_reason:
            self.failed.emit(self.block_reason)
            return
        self.worker = SimulationTaskWorker(self.context, action, payload, self.revision, self)
        self.worker.completed.connect(self._task_completed)
        self.worker.failed.connect(self._task_failed)
        self.worker.finished.connect(self._finished)
        self.busy_changed.emit(True)
        self.worker.start()

    def _task_completed(self, revision, action, result):
        if revision != self.revision:
            logger.info('Discarded obsolete simulation task: action=%s revision=%d', action, revision)
            return
        if action == 'execute':
            self.last_report = result['report']
            self.history = result['history']
            self.executed.emit(self.last_report, self.history)
        else:
            self.suggestions_ready.emit(result)

    def _task_failed(self, revision, message):
        if revision == self.revision:
            self.failed.emit(message)

    def _finished(self):
        worker = self.worker
        self.worker = None
        worker.deleteLater()
        self.busy_changed.emit(False)
