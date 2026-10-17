"""Exercise the optional Qt adapter with real services and isolated cache storage."""

import json
import logging
import os
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
pytest.importorskip('PySide6')

from PySide6.QtCore import QCoreApplication, QEvent, QThread  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from qt_compact_sample import sample_snapshot  # noqa: E402

from oci_policy_analysis.application.core.support import caching, config  # noqa: E402
from oci_policy_analysis.application.services.load_service import LoadResult, LoadService  # noqa: E402
from oci_policy_analysis.presentation.qt.main import WorkbenchWindow
from oci_policy_analysis.presentation.qt.profiles import profile_names  # noqa: E402


@pytest.fixture
def workbench(qt_application, monkeypatch, tmp_path, request):
    """Keep the application alive across tests and isolate cache/profile storage."""
    application = qt_application
    monkeypatch.setattr('oci_policy_analysis.presentation.qt.loading.sample_snapshot', sample_snapshot)
    monkeypatch.setattr(caching, 'CACHE_DIR', tmp_path / 'cache')
    monkeypatch.setattr(config, 'SETTINGS_PATH', str(tmp_path / 'settings.json'))
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.delenv('CODEX_HOME', raising=False)
    root_level = logging.getLogger().level
    levels = {
        name: logger.level
        for name, logger in logging.root.manager.loggerDict.items()
        if isinstance(logger, logging.Logger)
    }
    window = WorkbenchWindow(verbose=getattr(request, 'param', False))
    yield application, window
    _wait_for_load(application, window)
    _wait_for_simulation(application, window)
    _wait_for_reports(application, window)
    _wait_for_recommendations(application, window)
    _wait_for_historical(application, window)
    window.mcp_page.stop_all()
    deadline = time.monotonic() + 20
    while window.mcp_page.active and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.01)
    assert not window.mcp_page.active, 'MCP/Codex shutdown did not finish'
    window.close()
    application.processEvents()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    logging.getLogger().setLevel(root_level)
    for name, logger in logging.root.manager.loggerDict.items():
        if isinstance(logger, logging.Logger):
            logger.setLevel(levels.get(name, logging.NOTSET))


@pytest.fixture(scope='session')
def qt_application():
    """Keep QApplication alive until all test windows and scene items are deleted."""
    application = QApplication.instance() or QApplication([])
    yield application
    application.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _wait_for_load(application, window):
    deadline = time.monotonic() + 20
    while window.controller.worker is not None and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.01)
    assert window.controller.worker is None, 'Qt load did not finish'


def _wait_for_simulation(application, window):
    deadline = time.monotonic() + 20
    while window.simulation_page.controller.worker is not None and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.01)
    assert window.simulation_page.controller.worker is None, 'Statement preparation did not finish'


def _prepare_execution(workbench, operation_name='CreateBucket'):
    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    window.settings_page.advanced_mode.setChecked(True)
    window.navigation.setCurrentRow(window.page_index('simulation'))
    page = window.simulation_page
    page.principal.setCurrentText('Default/AppDevelopers')
    page.compartment.setCurrentText('ROOT/Applications')
    page.continue_button.click()
    _wait_for_simulation(application, window)
    page.statements.next.click()
    operation = next(row for row in page.request_context.catalog if row['operation_name'] == operation_name)
    page.request_context.operation.setCurrentText(operation['label'])
    return application, window, page


def test_simulation_execution_draft_review_and_rerun_history(workbench, monkeypatch):
    from copy import deepcopy

    from PySide6.QtWidgets import QDialog

    application, window, page = _prepare_execution(workbench)
    before = deepcopy(window.controller.context.policy_repo.regular_statements)
    original_ids = page.controller.checked_ids[:]
    page.request_context.run.click()
    _wait_for_simulation(application, window)
    assert page.currentIndex() == 3
    baseline = deepcopy(page.results.report)
    assert not baseline['result']['api_call_allowed']
    assert 'BUCKET_CREATE' in baseline['result']['missing_permissions']
    assert page.results.permissions.model.rowCount() > 0
    assert page.results.evidence.topLevelItemCount() == 1
    page.results.explore_policies.click()
    assert page.results.tabs.currentIndex() == 4
    page.results.generate.click()
    _wait_for_simulation(application, window)
    assert page.results.candidates.model.rowCount() == 1
    candidate = page.results.candidates.model.records[0]
    assert candidate['covered_permissions'] == ['BUCKET_CREATE']
    assert candidate['additional_permissions'] == []
    assert 'Allow group' in candidate['statement_text']

    def reviewed(dialog):
        assert 'BUCKET_CREATE' in dialog.statement.toPlainText()
        assert dialog.tabs.currentIndex() == 1
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr('oci_policy_analysis.presentation.qt.pages.prospective.ProspectiveEditorDialog.exec', reviewed)
    page.results.candidates.selectRow(0)
    page.results.add_prospects.click()
    _wait_for_simulation(application, window)
    assert page.currentIndex() == 2
    assert set(original_ids) <= set(page.controller.checked_ids)
    assert len(page.controller.checked_ids) == len(original_ids) + 1
    assert page.controller.api_operation == baseline['request']['api_operation']
    page.request_context.run.click()
    _wait_for_simulation(application, window)
    assert page.results.report['result']['api_call_allowed']
    assert len(page.controller.history) == 2
    assert page.controller.history[0]['workbench_report'] == baseline
    page.results.history.setCurrentIndex(0)
    assert page.results.report['result']['missing_permissions'] == ['BUCKET_CREATE']
    assert window.controller.context.policy_repo.regular_statements == before
    assert window.prospective_page.service.records.list_all()


def test_simulation_related_path_reprepares_and_history_covers_both(workbench):
    application, window, page = _prepare_execution(workbench, 'LaunchInstance')
    page.request_context.run.click()
    _wait_for_simulation(application, window)
    assert page.results.related.model.rowCount() >= 1
    page.results.explore_related.click()
    assert page.results.tabs.currentIndex() == 3
    related = next(
        row for row in page.results.related.model.records if row['api_operation'] == 'core:LaunchInstance (Subnet)'
    )
    page.results.related_operation.setCurrentText(related['api_operation'])
    page.results.related_button.click()
    assert page.controller.worker is None
    assert 'compartment' in page.results.status.text()
    page.results.related_path.setCurrentText('ROOT/Platform')
    page.results.related_button.click()
    _wait_for_simulation(application, window)
    assert page.currentIndex() == 2
    assert page.controller.scenario['compartment_path'] == 'ROOT/Platform'
    assert page.controller.api_operation == 'core:LaunchInstance (Subnet)'
    assert page.controller.checked_ids == []  # Application policy must not leak into network scope.
    page.request_context.run.click()
    _wait_for_simulation(application, window)
    report = page.results.report
    assert report['result']['missing_permissions'] == ['SUBNET_ATTACH']
    assert report['request']['where_context']['request.operation'] == 'LaunchInstance'
    assert report['request']['checked_statement_ids'] == []
    assert len(page.controller.history) == 2
    assert page.controller.history[0]['workbench_report']['request']['compartment_path'] == 'ROOT/Applications'
    assert page.controller.history[1]['workbench_report']['request']['compartment_path'] == 'ROOT/Platform'
    from oci_policy_analysis.application.services.simulation_workbench_service import SimulationWorkbenchService

    context = window.controller.context
    candidates = SimulationWorkbenchService(context).policy_candidates(
        report,
        principal_key=report['request']['principal_key'],
        granularity='permission',
        effective_path='ROOT/Platform',
        where_clause="request.operation = 'LaunchInstance'",
    )
    context.simulation.set_prospective_statements(candidates['candidates'])
    page.refresh_prospective()
    page.prepare_followup(report['request'], [])
    _wait_for_simulation(application, window)
    page.request_context.run.click()
    _wait_for_simulation(application, window)
    assert page.results.report['result']['api_call_allowed']
    assert page.results.report['request']['where_context']['request.operation'] == 'LaunchInstance'
    assert len(page.controller.history) == 3


def test_simulation_policy_candidates_granularity_restrictions_and_provenance(workbench):
    from copy import deepcopy

    from oci_policy_analysis.application.services.simulation_workbench_service import SimulationWorkbenchService

    application, window, page = _prepare_execution(workbench)
    context = window.controller.context
    service = SimulationWorkbenchService(context)
    report = service.execute(page.controller.request_payload())
    source = deepcopy(context.policy_repo.regular_statements)
    for mode in ('permission', 'resource', 'family'):
        result = service.policy_candidates(
            report,
            principal_key=page.controller.scenario['principal_key'],
            granularity=mode,
            effective_path='ROOT/Applications',
            where_clause="request.operation = 'CreateBucket'",
        )
        assert result['candidates'], (mode, result)
        assert not result['unmapped_permissions']
        for row in result['candidates']:
            assert 'where request.operation' in row['statement_text']
            assert context.simulation.validate_prospective_statement(row['statement_text'])['valid']
            assert row['mapping']
            if mode != 'permission':
                assert row['additional_permissions']
        assert 'guaranteed' in result['limitations']
    assert context.policy_repo.regular_statements == source
    assert not context.simulation.get_prospective_statements()
    assert len(service.history()) == 1  # Suggestions never create simulation runs.
    with pytest.raises(ValueError, match='ancestor'):
        service.policy_candidates(
            report,
            principal_key=page.controller.scenario['principal_key'],
            granularity='permission',
            effective_path='ROOT/Applications',
            policy_path='ROOT/Security',
        )
    with pytest.raises(ValueError, match='principal'):
        service.policy_candidates(
            report, principal_key='user:default/alice', granularity='permission', effective_path='ROOT/Applications'
        )
    with pytest.raises(ValueError, match='restriction'):
        service.policy_candidates(
            report,
            principal_key=page.controller.scenario['principal_key'],
            granularity='permission',
            effective_path='ROOT/Applications',
            where_clause='all {',
        )


def test_simulation_failed_conditions_denies_and_stale_input_results(workbench):
    from copy import deepcopy

    from oci_policy_analysis.application.services.simulation_workbench_service import SimulationWorkbenchService

    application, window, page = _prepare_execution(workbench, 'ListBuckets')
    context = window.controller.context
    original = next(row for row in context.policy_repo.regular_statements if row['resource'] == 'objects')
    grant = {
        **deepcopy(original),
        'internal_id': 'conditional-buckets',
        'resource': 'buckets',
        'verb': 'read',
        'conditions': "request.networkSource.name = 'trusted'",
        'statement_text': "Allow group AppDevelopers to read buckets in compartment Applications where request.networkSource.name = 'trusted'",
    }
    deny = {
        **deepcopy(grant),
        'internal_id': 'deny-buckets',
        'action': 'deny',
        'verb': 'inspect',
        'conditions': '',
        'statement_text': 'Deny group AppDevelopers to inspect buckets in compartment Applications',
    }
    grant['permission'] = context.reference_data.get_permissions('buckets', 'read')
    deny['permission'] = context.reference_data.get_permissions('buckets', 'inspect', action='deny')
    context.policy_repo.regular_statements.extend([grant, deny])
    context.simulation.set_corpus(None)
    request = page.controller.request_payload()
    request['checked_statement_ids'] = ['conditional-buckets', 'deny-buckets']
    report = SimulationWorkbenchService(context).execute(request)
    assert not report['result']['api_call_allowed']
    assert report['comparisons']
    assert any('conditions did not pass' in text for text in report['findings'])
    assert any('cannot override' in text for text in report['findings'])
    assert any(row['status'] == 'Denied by statement' for row in report['permissions'])
    page.results.show_report(report)
    assert page.results.evidence.topLevelItemCount() == 2
    page.request_context.search.setText('CreateBucket')
    assert 'inputs changed' in page.results.current_status.text()
    old_history = deepcopy(context.simulation.simulation_history)
    invalid = {**request, 'checked_statement_ids': ['no-such-statement']}
    with pytest.raises(ValueError, match='no longer eligible'):
        SimulationWorkbenchService(context).execute(invalid)
    assert context.simulation.simulation_history == old_history


def test_simulation_history_export_cancelled_draft_and_snapshot_reset(workbench, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QDialog

    from oci_policy_analysis.application.services.simulation_workbench_service import SimulationWorkbenchService

    application, window, page = _prepare_execution(workbench)
    window._mcp_locked(True)
    page.request_context.run.click()
    assert page.controller.worker is None
    assert not window.controller.context.simulation.simulation_history
    window._mcp_locked(False)
    page.request_context.run.click()
    _wait_for_simulation(application, window)
    report = page.results.report
    page.results.generate.click()
    _wait_for_simulation(application, window)
    monkeypatch.setattr(
        'oci_policy_analysis.presentation.qt.pages.prospective.ProspectiveEditorDialog.exec',
        lambda _dialog: QDialog.DialogCode.Rejected,
    )
    page.results.candidates.selectRow(0)
    page.results.add_prospects.click()
    assert not window.prospective_page.service.records.list_all()
    assert len(page.controller.history) == 1
    path = tmp_path / 'runs.json'
    monkeypatch.setattr(
        'oci_policy_analysis.presentation.qt.pages.simulation_results.QFileDialog.getSaveFileName',
        lambda *_args: (str(path), 'JSON'),
    )
    page.results._export()
    exported = json.loads(path.read_text())
    assert (
        exported[0]['workbench_report']['request']['checked_statement_ids']
        == report['request']['checked_statement_ids']
    )
    service = SimulationWorkbenchService(window.controller.context)
    detached = service.history()
    detached[0]['workbench_report']['result']['missing_permissions'].clear()
    assert service.history()[0]['workbench_report']['result']['missing_permissions']
    multi = {**report, 'result': {**report['result'], 'missing_permissions': ['BUCKET_CREATE', 'INSTANCE_CREATE']}}
    generated = service.policy_candidates(
        multi,
        principal_key=report['request']['principal_key'],
        granularity='resource',
        effective_path='ROOT/Applications',
    )
    assert len(generated['candidates']) >= 2
    evidence_report = {**report, 'result': {**report['result'], 'missing_permissions': ['OBJECT_READ']}}
    provenance = service.policy_candidates(
        evidence_report,
        principal_key=report['request']['principal_key'],
        granularity='permission',
        effective_path='ROOT/Applications',
    )
    assert any(row['internal_id'] == report['request']['checked_statement_ids'][0] for row in provenance['evidence'])
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    assert page.results.report is None
    assert not page.controller.history
    with pytest.raises(ValueError, match='previous snapshot'):
        SimulationWorkbenchService(window.controller.context).policy_candidates(
            report,
            principal_key=report['request']['principal_key'],
            granularity='permission',
            effective_path='ROOT/Applications',
        )


def test_simulation_request_schema_retains_conditions_and_diagnostics(workbench):
    from copy import deepcopy

    from oci_policy_analysis.application.services.simulation_service import SimulationService

    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    statements = [
        {
            'internal_id': 'a',
            'conditions': 'all {request.principal.id = target.bucket.owner.id, !request.principal.type}',
        },
        {'internal_id': 'b', 'conditions': {'raw_text': "request.operation = 'ListBuckets'"}},
        {
            'internal_id': 'c',
            'statement_text': "Allow group A to read buckets in tenancy where request.region = 'us-ashburn-1'",
        },
        {'internal_id': 'd', 'conditions': 'all {'},
    ]
    before = deepcopy(statements)
    result = SimulationService(window.controller.context).request_context_schema(statements)
    assert set(result['variables']) == {
        'request.principal.id',
        'target.bucket.owner.id',
        'request.principal.type',
        'request.operation',
        'request.region',
    }
    unsupported = next(row for row in result['conditions'] if row['internal_id'] == 'd')
    assert unsupported['parse_status'] == 'unsupported'
    assert unsupported['warnings']
    assert statements == before


def test_simulation_request_context_operations_subset_values_and_reload(workbench):
    from copy import deepcopy

    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    window.settings_page.advanced_mode.setChecked(True)
    window.navigation.setCurrentRow(window.page_index('simulation'))
    context = window.controller.context
    source = next(row for row in context.policy_repo.regular_statements if row['resource'] == 'objects')
    source['conditions'] = "all {request.networkSource.name = 'trusted', request.operation = 'ListBuckets'}"
    extra = {
        **deepcopy(source),
        'internal_id': 'request-extra',
        'conditions': "all {request.networkSource.name = 'trusted', request.region = 'us-ashburn-1'}",
    }
    context.policy_repo.regular_statements.append(extra)
    context.simulation.set_corpus(None)
    page = window.simulation_page
    page.principal.setCurrentText('Default/AppDevelopers')
    page.compartment.setCurrentText('ROOT/Applications')
    page.continue_button.click()
    _wait_for_simulation(application, window)
    page.statements.next.click()
    assert page.currentIndex() == 2
    request = page.request_context
    assert set(request.input_widgets) == {'request.networkSource.name', 'request.region'}
    assert 'request.operation' not in request.input_widgets
    request.search.setText('ChangeInstanceCompartment')
    operation = next(row for row in request.catalog if row['operation_name'] == 'ChangeInstanceCompartment')
    request.operation.setCurrentText(operation['label'])
    assert page.controller.api_operation == operation['label']
    assert 'INSTANCE_MOVE' in request.metadata.toPlainText()
    assert request.related.model.rowCount() > 0
    assert request.related.model.records[0]['applies_when']
    value, null = request.input_widgets['request.networkSource.name']
    value.setText('trusted')
    assert page.controller.request_payload()['where_context']['request.operation'] == 'ChangeInstanceCompartment'
    assert page.controller.request_payload()['where_context']['request.networkSource.name'] == 'trusted'
    assert 'request.region' not in page.controller.request_payload()['where_context']
    null.setChecked(True)
    assert 'request.networkSource.name' not in page.controller.request_payload()['where_context']
    null.setChecked(False)
    assert page.controller.request_payload()['where_context']['request.networkSource.name'] == 'trusted'
    page.setCurrentIndex(1)
    page.statements.selection.model.set_checked_ids([source['internal_id']])
    assert set(request.input_widgets) == {'request.networkSource.name'}
    assert request.input_widgets['request.networkSource.name'][0].text() == 'trusted'
    page.statements.next.click()
    assert request.operation.currentText() == operation['label']
    request.copy.click()
    assert json.loads(application.clipboard().text())['checked_statement_ids'] == [source['internal_id']]
    page.statements.selection.model.set_checked_ids([])
    assert not request.input_widgets
    assert page.controller.request_payload()['checked_statement_ids'] == []
    assert 'request.networkSource.name' not in page.controller.request_payload()['where_context']
    request.search.setText('no-such-operation')
    assert page.controller.api_operation == ''
    assert not request.copy.isEnabled()
    assert not context.simulation.simulation_history
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    assert not request.input_widgets
    assert page.controller.api_operation == ''
    assert page.controller.where_values == {}
    assert not page.isTabEnabled(2)


def test_simulation_statement_selection_preserves_checks_and_invalidates(workbench):
    from copy import deepcopy

    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    window.settings_page.advanced_mode.setChecked(True)
    window.navigation.setCurrentRow(window.page_index('simulation'))
    page = window.simulation_page
    page.principal.setCurrentText('Default/AppDevelopers')
    page.compartment.setCurrentText('ROOT/Applications')
    before = deepcopy(window.controller.context.policy_repo.regular_statements)
    page.continue_button.click()
    assert page.controller.worker is not None
    assert window.controller.load_block_reason
    assert not window.prospective_page.isEnabled()
    _wait_for_simulation(application, window)
    assert page.controller.ready
    assert page.currentIndex() == 1
    selection = page.statements.selection
    assert selection.model.rowCount() == 1
    ids = selection.model.checked_ids()
    assert len(ids) == 1
    assert page.controller.checked_ids == ids
    page.statements.search.setText('no-matching-statement')
    assert selection.table.proxy.rowCount() == 0
    assert '1 checked outside filter' in selection.counts.text()
    selection._visible(False)
    assert selection.model.checked_ids() == ids
    page.statements.search.clear()
    selection.model.set_checked_ids([])
    assert page.controller.checked_ids == []
    assert 'explicit empty selection' in page.statements.status.text()
    page.setCurrentIndex(0)
    page.continue_button.click()
    assert page.controller.worker is None  # Returning does not silently re-check rows.
    assert selection.model.checked_ids() == []
    assert page.currentIndex() == 1
    page.statements.next.click()
    assert page.currentIndex() == 2
    page.setCurrentIndex(0)
    page.principal.setCurrentText('Default/Auditors')
    assert not page.controller.ready
    assert selection.model.rowCount() == 0
    assert not page.isTabEnabled(2)
    assert window.controller.context.policy_repo.regular_statements == before
    assert not window.controller.context.simulation.simulation_history


def test_simulation_candidates_retain_exclusions_and_source_identity(workbench, caplog):
    from copy import deepcopy

    from oci_policy_analysis.application.services.simulation_service import SimulationService

    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    context = window.controller.context
    original = next(row for row in context.policy_repo.regular_statements if row['resource'] == 'objects')
    invalid = {
        **deepcopy(original),
        'internal_id': 'invalid-copy',
        'valid': False,
        'invalid_reasons': ['Invalid example'],
    }
    missing = {**deepcopy(original), 'internal_id': ''}
    context.policy_repo.regular_statements.extend([invalid, missing])
    context.simulation.set_corpus(None)
    before = deepcopy(context.policy_repo.regular_statements)
    service = SimulationService(context)
    result = service.statement_candidates(
        compartment_path='ROOT/Applications', principal_type='group', principal=('Default', 'AppDevelopers')
    )
    rows = {row['internal_id']: row for row in result['statements']}
    assert result['principal_key'] == 'group:default/appdevelopers'
    assert rows[original['internal_id']]['checkable']
    assert not rows['invalid-copy']['checkable']
    assert not rows['']['checkable']
    assert rows['invalid-copy']['source_kind'] == 'Collected'
    assert rows[original['internal_id']] is not original
    assert context.policy_repo.regular_statements == before
    context.policy_repo.regular_statements.append(deepcopy(original))
    with caplog.at_level(logging.INFO):
        deduplicated = service.statement_candidates(
            compartment_path='ROOT/Applications', principal_type='group', principal=('Default', 'AppDevelopers')
        )
    assert len(deduplicated['statements']) == len(result['statements'])
    assert 'duplicate' in caplog.text.lower()
    assert 'stage=source' in caplog.text
    assert len(context.policy_repo.regular_statements) == len(before) + 1
    # A collision outside this environment is also unsafe: execution resolves
    # explicit IDs from the whole snapshot, not just the displayed candidates.
    context.policy_repo.regular_statements[-1]['effective_path'] = 'ROOT/OtherScope'
    with pytest.raises(ValueError, match='Duplicate statement ID'):
        service.statement_candidates(
            compartment_path='ROOT/Applications', principal_type='group', principal=('Default', 'AppDevelopers')
        )


def test_simulation_duplicate_source_advances_and_logs_in_live_view(workbench, monkeypatch):
    from copy import deepcopy

    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    window.settings_page.advanced_mode.setChecked(True)
    window.navigation.setCurrentRow(window.page_index('simulation'))
    panel = window.settings_page.logging_panel
    panel.refresh_components()
    assert 'qt.simulation' in panel.levels
    assert 'application.services.simulation' in panel.levels
    window.live_log.scope.setCurrentText('Simulation')
    window.live_log._clear()
    context = window.controller.context
    original = next(row for row in context.policy_repo.regular_statements if row['resource'] == 'objects')
    context.policy_repo.regular_statements.append(deepcopy(original))
    before = deepcopy(context.policy_repo.regular_statements)
    # Repeated query rows must also collapse independently of source de-duplication.
    prepare = type(context.simulation).get_statements_for_context

    def repeated(engine, *args):
        key, rows = prepare(engine, *args)
        return key, rows + deepcopy(rows)

    monkeypatch.setattr(type(context.simulation), 'get_statements_for_context', repeated)
    page = window.simulation_page
    page.principal.setCurrentText('Default/AppDevelopers')
    page.compartment.setCurrentText('ROOT/Applications')
    page.continue_button.click()
    _wait_for_simulation(application, window)
    assert page.controller.ready
    assert page.currentIndex() == 1
    assert page.statements.selection.model.rowCount() == 1
    assert len(page.controller.checked_ids) == 1
    window.log_bridge.flush()
    output = window.live_log.output.toPlainText()
    assert 'qt.simulation' in output
    assert 'application.services.simulation' in output
    assert 'stage=source' in output
    assert 'stage=candidates' in output
    assert 'candidates=1' in output
    assert context.policy_repo.regular_statements == before
    assert not context.simulation.simulation_history
    context.policy_repo.regular_statements[-1]['statement_text'] += ' conflicting source'
    page.controller.set_environment(page.scenario, force=True)
    page.continue_button.click()
    _wait_for_simulation(application, window)
    assert not page.controller.ready
    window.log_bridge.flush()
    output = window.live_log.output.toPlainText()
    assert 'Duplicate statement ID conflict' in output
    assert 'differing_fields' in output
    assert 'preparation failed' in output


def test_simulation_preparation_blocks_mcp_and_rejects_obsolete_results(workbench, monkeypatch):
    from oci_policy_analysis.application.services.simulation_service import SimulationService

    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    page = window.simulation_page
    page.controller.block_reason = 'Stop embedded MCP before preparing simulation statements.'
    page.controller.prepare()
    assert page.controller.worker is None
    assert 'Stop embedded MCP' in page.preparation_status.text()
    page.controller.block_reason = ''
    started, release = threading.Event(), threading.Event()
    original = SimulationService.statement_candidates

    def delayed(service, **kwargs):
        started.set()
        assert release.wait(5)
        return original(service, **kwargs)

    monkeypatch.setattr(SimulationService, 'statement_candidates', delayed)
    page.controller.prepare()
    try:
        assert started.wait(5)
        window.controller.start_load('sample', {}, 'Blocked concurrent reload')
        assert window.controller.worker is None
        window.mcp_page.start_server()
        assert not window.mcp_page.active
        window.close()
        assert page.controller.worker is not None
        page.controller.set_environment(None, force=True)
    finally:
        release.set()
    _wait_for_simulation(application, window)
    assert not page.controller.ready
    assert page.statements.selection.model.rowCount() == 0
    assert page.controller.checked_ids == []


def test_simulation_candidates_include_prospective_and_explain_invalid_drafts(workbench):
    from oci_policy_analysis.application.services.simulation_service import SimulationService

    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    context = window.controller.context
    context.simulation.set_prospective_statements(
        [
            {
                'internal_id': 'prospective-valid',
                'compartment_path': 'ROOT/Applications',
                'statement_text': 'Allow group AppDevelopers to manage objects in compartment Applications',
            },
            {
                'internal_id': 'prospective-invalid',
                'compartment_path': 'ROOT/Security',
                'statement_text': 'this is an invalid local draft',
            },
        ]
    )
    result = SimulationService(context).statement_candidates(
        compartment_path='ROOT/Applications', principal_type='group', principal=('Default', 'AppDevelopers')
    )
    prospects = [row for row in result['statements'] if row['source_kind'] == 'Prospective']
    assert len(prospects) == 2
    assert any(row['checkable'] for row in prospects)
    draft = next(row for row in prospects if not row['checkable'])
    assert draft['scope_status'] == 'Unverified draft'
    assert draft['selection_reason']
    assert draft['statement_text'] == 'this is an invalid local draft'
    page = window.simulation_page
    page.refresh_prospective()
    page.principal.setCurrentText('Default/AppDevelopers')
    page.compartment.setCurrentText('ROOT/Applications')
    page.continue_button.click()
    _wait_for_simulation(application, window)
    ids = page.controller.checked_ids[:]
    page.refresh_prospective()
    assert page.controller.checked_ids == ids
    context.simulation.set_prospective_statements([])
    page.refresh_prospective()
    assert not page.controller.ready
    assert page.controller.checked_ids == []


def test_simulation_environment_uses_snapshot_choices_and_resets(workbench):
    application, window = workbench
    page = window.simulation_page
    assert page.scenario is None
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    assert page.count() == 4
    assert page.scenario['principal_type'] == 'group'
    assert page.scenario['principal_key'].startswith('group:default/')
    page.principal_type.setCurrentText('dynamic-group')
    labels = [page.principal.itemText(i) for i in range(page.principal.count())]
    assert 'Default/AppWorkers' in labels
    assert 'Operations/AppWorkers' in labels
    page.principal.setCurrentText('Operations/AppWorkers')
    assert page.scenario['principal_key'] == 'dynamic-group:operations/appworkers'
    page.compartment.setCurrentText('ROOT/Security')
    page.principal_type.setCurrentText('any-user')
    assert not page.principal.isEnabled()
    assert page.scenario['principal_key'] == 'any-user:none/any-user'
    assert page.principal_type.findText('user') == -1
    page.setCurrentIndex(2)
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    assert page.currentIndex() == 0
    assert page.scenario['principal_type'] == 'group'
    assert page.scenario['compartment_path'] != 'ROOT/Security'
    window.settings_page.advanced_mode.setChecked(True)
    window.navigation.setCurrentRow(window.page_index('simulation'))
    page.manage.click()
    assert window.pages.currentWidget() is window.prospective_page


def test_simulation_environment_options_preserve_source_and_opaque_ids(workbench):
    from copy import deepcopy

    from oci_policy_analysis.application.services.simulation_service import SimulationService

    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    context = window.controller.context
    source = {
        'subject_type': 'group-id',
        'subject': ['ocid1.group.OpaqueCASE'],
        'valid': False,
    }
    context.policy_repo.regular_statements.append(source)
    before = deepcopy(context.policy_repo.regular_statements)
    options = SimulationService(context).environment_options()
    assert options['principals']['group-id'][0]['principal_key'] == 'group-id:None/ocid1.group.OpaqueCASE'
    assert context.policy_repo.regular_statements == before
    context.policy_repo.compartments.clear()
    window.simulation_page.set_context(context)
    assert window.simulation_page.scenario is None
    assert 'Missing inventory' in window.simulation_page.summary.text()


def test_sample_load_navigation_and_filtered_source_evidence(workbench):
    application, window = workbench
    assert window.controller.context is None
    window.settings_page.load_sample()
    assert not window.settings_page.load_button.isEnabled()
    _wait_for_load(application, window)
    assert window.controller.context is not None
    assert window.controller.context.corpus is not None
    assert window.settings_page.counts['policies'].text() == '5'
    assert window.browser_page.model.rowCount() == 6
    window.navigation.setCurrentRow(window.page_index('browser'))
    assert window.pages.currentIndex() == window.page_index('browser')
    window.browser_page.search.setText('corporate-network')
    assert window.browser_page.proxy.rowCount() == 1
    window.browser_page.table.selectRow(0)
    assert window.drawer.record is None
    menu = window.browser_page.table.context_menu(
        window.browser_page.table.record_at(window.browser_page.proxy.index(0, 0))
    )
    menu.actions()[0].trigger()
    menu.deleteLater()
    assert "request.networkSource.name = 'corporate-network'" in window.drawer.raw.toPlainText()
    assert 'Synthetic sample' in window.settings_page.snapshot_label.text()
    assert window.settings_page.load_button.isEnabled()
    assert not list(window.controller.context.cache.cache_dir.glob('*.json'))


def test_export_is_unchanged_and_failed_reload_retains_snapshot(workbench, tmp_path):
    application, window = workbench
    path = tmp_path / 'export.json'
    original = json.dumps(sample_snapshot()).encode()
    path.write_bytes(original)
    window.controller.start_load('file', {'path': str(path)}, 'Test export')
    _wait_for_load(application, window)
    previous = window.controller.context
    assert previous is not None
    assert path.read_bytes() == original
    window.controller.start_load('file', {'path': str(tmp_path / 'missing.json')}, 'Missing file')
    _wait_for_load(application, window)
    assert window.controller.context is previous
    assert window.browser_page.model.rowCount() == 6
    assert window.log_dock.isHidden()
    assert 'Load failed' in window.settings_page.load_status.text()
    assert 'Previous snapshot retained' in window.activity_page.toPlainText()


def test_selected_profile_is_loaded_in_worker_with_cache_saving_enabled(workbench, monkeypatch):
    application, window = workbench
    captured = {}

    def load(self, **kwargs):
        captured.update(kwargs)
        captured['thread'] = QThread.currentThread()
        return LoadResult(True, 'Test load', {})

    monkeypatch.setattr(LoadService, 'load_from_tenancy', load)
    window.settings_page.profile.setCurrentText('TEAM')
    window.settings_page.depth.setValue(2)
    window.settings_page.recursive.setChecked(False)
    window.settings_page.load_button.click()
    _wait_for_load(application, window)
    assert captured['thread'] != application.thread()
    assert captured['profile'] == 'TEAM'
    assert captured['recursive'] is False
    assert captured['compartment_domain_search_depth'] == 2
    assert captured['save_cache_after_load'] is True
    assert captured['post_load_profile'] == 'minimal'


def test_profile_discovery_reads_names_without_interpolating_values(tmp_path):
    path = tmp_path / 'config'
    path.write_text('[DEFAULT]\nuser=example\n[TEAM]\nkey_file=path-with-%-character\n', encoding='utf-8')
    assert profile_names(path) == ['DEFAULT', 'TEAM']


def test_core_browser_filters_and_graph_evidence(workbench):
    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    browser = window.browser_page
    browser.filters['resource'].setText('secret-bundles')
    browser.filters['conditions'].setText('corporate-network')
    browser.filters['permission'].setText('SECRET_BUNDLE_READ')
    browser.apply_filters()
    assert browser.model.rowCount() == 1
    browser.reset_filters()
    assert browser.model.rowCount() == 6
    graph = window.graph_page
    assert graph.result['total'] > 0
    graph.filters['resource'].setText('SECRET_BUNDLE_READ')
    graph.search()
    assert graph.visible_grants
    assert all('SECRET_BUNDLE_READ' in grant['permissions'] for grant in graph.visible_grants)
    assert 'corporate-network' in graph.visible_grants[0]['condition_clause']
    nodes = [
        item for item in graph.scene.items() if isinstance(item.data(0), dict) and 'statement_text' in item.data(0)
    ]
    assert nodes
    nodes[0].setSelected(True)
    assert 'corporate-network' in graph.detail.toPlainText()
    assert graph.statements.model.rowCount() == 1
    assert window.drawer.record is None
    record = graph.statements.model.records[0]
    assert record['permission_facts']
    assert any(fact['permission'] == 'SECRET_BUNDLE_READ' for fact in record['permission_facts'])
    menu = graph.statements.context_menu(record)
    menu.actions()[0].trigger()
    menu.deleteLater()
    assert window.drawer.record is record
    assert 'permission_facts' in window.drawer.raw.toPlainText()
    assert 'corporate-network' in window.drawer.raw.toPlainText()
    old_corpus = window.controller.context.corpus
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    assert window.graph_page.context.corpus is not old_corpus
    assert window.graph_page.visible_grants


def test_qt_logging_levels_are_reversible_survive_reload_and_detach(workbench):
    application, window = workbench
    panel = window.settings_page.logging_panel
    window.settings_page.sections['Logging'].button.click()
    assert not panel.isHidden()
    assert panel.levels['global'].findText('DEBUG') == -1
    panel.levels['qt.main'].setCurrentText('DEBUG')
    panel.apply_levels()
    logger = logging.getLogger('oci-policy-analysis.qt.main')
    logger.debug('debug UI exclusion marker')
    logger.info('info UI visibility marker')
    window.log_bridge.flush()
    application.processEvents()
    assert 'debug UI exclusion marker' not in window.live_log.output.toPlainText()
    assert 'info UI visibility marker' in window.live_log.output.toPlainText()
    panel.levels['global'].setCurrentText('WARNING')
    panel.levels['qt.main'].setCurrentText('ERROR')
    panel.apply_levels()
    assert logging.getLogger().level == logging.WARNING
    logger = logging.getLogger('oci-policy-analysis.qt.main')
    assert logger.getEffectiveLevel() == logging.ERROR
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    assert logger.getEffectiveLevel() == logging.ERROR
    logger.debug('must stay hidden after reload')
    logger.error('visible test error')
    window.log_bridge.flush()
    application.processEvents()
    assert 'must stay hidden' not in window.live_log.output.toPlainText()
    assert 'visible test error' in window.live_log.output.toPlainText()
    handler = window.log_bridge.handler
    assert handler in logging.getLogger().handlers
    window.close()
    assert handler not in logging.getLogger().handlers


def test_graph_pagination_exclusions_and_unresolved_source_survive_import(workbench, tmp_path):
    application, window = workbench
    snapshot = sample_snapshot()
    template = snapshot['policy_statements'][1]
    for index in range(15):
        snapshot['policy_statements'].append({**template, 'internal_id': f'extra-{index}'})
    snapshot['policy_statements'].append(
        {
            **template,
            'internal_id': 'invalid-evidence',
            'verb': 'unsupported-verb',
            'statement_text': 'Retained invalid source statement',
        }
    )
    path = tmp_path / 'partial.json'
    path.write_text(json.dumps(snapshot))
    window.controller.start_load('file', {'path': str(path)}, 'Partial test snapshot')
    _wait_for_load(application, window)
    graph = window.graph_page
    assert len(graph.visible_grants) == 12
    assert graph.next.isEnabled()
    graph.next.click()
    assert graph.page == 2
    assert graph.previous.isEnabled()
    nodes = [
        item
        for item in graph.scene.items()
        if isinstance(item.data(0), dict) and str(item.data(0).get('statement_id', '')).startswith('extra-')
    ]
    assert nodes
    nodes[0].setSelected(True)
    assert graph.statements.model.rowCount() == 16
    assert all(record['permission_facts'] for record in graph.statements.model.records)
    graph.previous.click()
    assert graph.statements.model.rowCount() == 0
    assert 'invalid-evidence' in graph.exclusions.toPlainText()
    assert window.browser_page.model.rowCount() == 22
    window.browser_page.validity.setCurrentIndex(2)
    window.browser_page.apply_filters()
    assert window.browser_page.model.rowCount() == 1


def test_settings_start_collapsed_and_widgets_apply_session_values(workbench):
    application, window = workbench
    page = window.settings_page
    assert window.navigation.count() == 13
    assert page.results.isHidden()
    assert window.log_dock.isHidden()
    assert not window.windowIcon().isNull()
    assert list(page.sections) == ['Logging', 'Intelligence', 'Look and Feel']
    assert all(not section.button.isChecked() and section.content.isHidden() for section in page.sections.values())
    page.appearance_panel.font_size.setCurrentText('Large')
    page.appearance_panel.compact.setChecked(True)
    page.appearance_panel.apply_settings()
    assert 'font-size: 15px' in window.styleSheet()
    assert window.browser_page.table.verticalHeader().defaultSectionSize() == 30
    page.intelligence_panel.profile.setCurrentIndex(1)
    page.intelligence_panel.where_reduction.setCurrentText('75%')
    page.intelligence_panel.apply_settings()
    assert window.controller.settings['qt_post_load_profile'] == 'full'
    assert window.controller.settings['risk_where_clause_reduction_pct'] == 75
    window.mcp_page.port.setValue(9876)
    assert window.controller.settings['mcp_port'] == 9876


def test_live_log_stays_available_while_tenancy_load_is_running(workbench, monkeypatch):
    application, window = workbench
    entered = threading.Event()
    release = threading.Event()
    captured = {}

    def load(self, **kwargs):
        captured.update(kwargs)
        kwargs['on_stage']('Loading policies', 'Fetching policy inventory', 'running')
        logging.getLogger('oci-policy-analysis.qt.load').info('worker progress marker')
        entered.set()
        if not release.wait(5):
            raise RuntimeError('test load timed out')
        return LoadResult(True, 'Test load', {})

    monkeypatch.setattr(LoadService, 'load_from_tenancy', load)
    window.settings_page.intelligence_panel.profile.setCurrentIndex(1)
    window.settings_page.intelligence_panel.apply_settings()
    window.settings_page.load_all_users.setChecked(False)
    window.settings_page.load_button.click()
    try:
        deadline = time.monotonic() + 3
        while not entered.is_set() and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(0.01)
        assert entered.is_set()
        application.processEvents()
        window.log_bridge.flush()
        assert window.log_dock.isHidden()
        window.settings_page.show_log.click()
        assert not window.log_dock.isHidden()
        assert window.live_log.output.isEnabled()
        assert not window.settings_page.load_button.isEnabled()
        assert 'worker progress marker' in window.live_log.output.toPlainText()
        assert 'Fetching policy inventory' in window.settings_page.load_status.text()
        assert captured['post_load_profile'] == 'full'
        assert captured['load_all_users'] is False
        window.navigation.setCurrentRow(window.page_index('browser'))
        assert not window.log_dock.isHidden()
    finally:
        release.set()
        _wait_for_load(application, window)
    assert not window.settings_page.results.isHidden()


@pytest.mark.parametrize('workbench', [True], indirect=True)
def test_verbose_is_cli_locked_and_debug_never_reaches_ui(workbench, caplog):
    application, window = workbench
    panel = window.settings_page.logging_panel
    assert window.verbose
    assert logging.getLogger().level == logging.DEBUG
    assert not panel.apply_button.isEnabled()
    assert all(not combo.isEnabled() for combo in panel.levels.values())
    logger = logging.getLogger('oci-policy-analysis.qt.main')
    logger.debug('CLI debug marker')
    logger.info('CLI info marker')
    window.log_bridge.flush()
    assert any(record.getMessage() == 'CLI debug marker' for record in caplog.records)
    assert 'CLI debug marker' not in window.live_log.output.toPlainText()
    assert 'CLI info marker' in window.live_log.output.toPlainText()


def test_ui_log_queue_is_bounded_and_flushes_in_batches(workbench):
    _, window = workbench
    bridge = window.log_bridge
    bridge.clear()
    record = logging.LogRecord('oci-policy-analysis.qt.load', logging.DEBUG, __file__, 1, 'debug', (), None)
    for _ in range(5005):
        bridge.handler.emit(record)
    assert bridge.handler.pending.empty()
    record.levelno = logging.INFO
    record.levelname = 'INFO'
    for _ in range(5005):
        bridge.handler.emit(record)
    assert bridge.handler.pending.qsize() == 5000
    bridge.flush()
    assert bridge.handler.pending.qsize() == 4900
    assert '5 log records omitted' in window.live_log.output.toPlainText()


def _wait_until(application, predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.01)
    assert predicate()


def test_policy_filters_apply_without_enter_or_apply_button(workbench):
    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    browser = window.browser_page
    browser.filters['resource'].setText('secret-bundles')
    _wait_until(application, lambda: browser.model.rowCount() == 1)
    browser.reset_filters()
    browser.verb.setCurrentText('manage')
    _wait_until(application, lambda: browser.model.rowCount() == 2)


def test_dynamic_groups_multi_selection_exact_domains_and_live_filters(workbench):
    from PySide6.QtCore import QItemSelectionModel

    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    page = window.dynamic_groups_page
    assert page.group_table.model.rowCount() == 3
    assert page.statements.model.rowCount() == 0
    selection = page.group_table.selectionModel()
    flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    for row in range(page.group_table.proxy.rowCount()):
        index = page.group_table.proxy.index(row, 0)
        if page.group_table.record_at(index)['domain_name'] == 'Default':
            selection.select(index, flags)
    assert len(page.group_table.selected_records()) == 2
    assert page.statements.model.rowCount() == 2
    page.filters['dynamic_group_name'].setText('AppWorkers')
    _wait_until(application, lambda: page.group_table.model.rowCount() == 2)
    assert len(page.group_table.selected_records()) == 1
    assert page.statements.model.rowCount() == 1
    page.filters['domain_name'].setText('Operations')
    _wait_until(application, lambda: page.group_table.model.rowCount() == 1)
    page.group_table.selectRow(0)
    assert page.statements.model.rowCount() == 0  # same name in another domain
    page.reset_filters()
    assert page.group_table.model.rowCount() == 3
    assert page.statements.model.rowCount() == 0
    page.group_table.clearSelection()
    assert not page.group_table.selected_records()
    assert page.statements.model.rowCount() == 0


def test_statement_context_action_focuses_known_dynamic_groups(workbench):
    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    statement = next(
        record for record in window.browser_page.model.records if record['subject_type'] == 'dynamic-group'
    )
    menu = window.browser_page.table.context_menu(statement)
    action = next(action for action in menu.actions() if action.text() == 'Focus on Dynamic Group')
    action.trigger()
    assert window.navigation.currentRow() == window.page_index('dynamic_groups')
    page = window.dynamic_groups_page
    assert len(page.group_table.selected_records()) == 1
    assert page.group_table.selected_records()[0]['domain_name'] == 'Default'
    assert page.statements.model.rowCount() == 1
    menu.deleteLater()
    regular = next(record for record in window.browser_page.model.records if record['subject_type'] == 'group')
    menu = window.browser_page.table.context_menu(regular)
    assert not any(action.text() == 'Focus on Dynamic Group' for action in menu.actions())
    menu.deleteLater()
    page.filters['domain_name'].setText('Operations')
    assert page.focus_statement({'subject_type': 'dynamic-group-id', 'subject': ['sample-dg-network']})
    assert page.group_table.selected_records()[0]['dynamic_group_name'] == 'NetworkWorkers'
    assert not page.focus_statement({'subject_type': 'dynamic-group-id', 'subject': ['SAMPLE-DG-NETWORK']})
    assert not page.group_table.selected_records()
    assert page.statements.model.rowCount() == 0


def test_shared_drawer_retains_all_evidence_and_clears_on_navigation_and_reload(workbench):
    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    window.show()
    window.navigation.setCurrentRow(window.page_index('browser'))
    window.browser_page.table.selectRow(0)
    assert not window.drawer.isVisible()
    menu = window.browser_page.table.context_menu(
        window.browser_page.table.record_at(window.browser_page.proxy.index(0, 0))
    )
    menu.actions()[0].trigger()
    menu.deleteLater()
    assert window.drawer.isVisible()
    record = {
        'statement_text': '<tag> original policy',
        'valid': False,
        'parsed': True,
        'invalid_reasons': ['unresolved principal'],
        'subject': [['Default', 'Missing']],
        'extra_evidence': {'preserved': True},
    }
    window.drawer.show_record(record)
    assert json.loads(window.drawer.raw.toPlainText()) == record
    assert window.drawer.status.text() == 'Invalid · Parsed: Yes'
    window.drawer.dismiss()
    _wait_until(application, lambda: not window.drawer.isVisible())
    # Ordinary clicks remain selection-only; explicit context action reopens it.
    window.browser_page.table.clicked.emit(window.browser_page.proxy.index(0, 0))
    assert not window.drawer.isVisible()
    menu = window.browser_page.table.context_menu(
        window.browser_page.table.record_at(window.browser_page.proxy.index(0, 0))
    )
    menu.actions()[0].trigger()
    menu.deleteLater()
    assert window.drawer.isVisible()
    window.navigation.setCurrentRow(window.page_index('dynamic_groups'))
    assert window.drawer.record is None
    table = window.dynamic_groups_page.group_table
    table.selectRow(0)
    assert not window.drawer.isVisible()
    menu = table.context_menu(table.record_at(table.proxy.index(0, 0)))
    menu.actions()[0].trigger()
    menu.deleteLater()
    assert window.drawer.title.text() == 'Dynamic group details'
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    assert window.drawer.record is None
    assert not window.drawer.isVisible()
    assert window.dynamic_groups_page.statements.model.rowCount() == 0


def test_themes_cover_graph_drawer_widgets_and_persist_across_restart(workbench):
    from PySide6.QtGui import QPalette

    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    context = window.controller.context
    appearance = window.settings_page.appearance_panel
    Path(config.SETTINGS_PATH).write_text(json.dumps({'unrelated_preference': 'preserved'}))
    appearance.theme.setCurrentText('Dark')
    appearance.color_theme.setCurrentText('Ocean')
    appearance.apply_settings()
    assert window.controller.context is context
    from oci_policy_analysis.presentation.qt.themes import theme_color

    assert application.palette().color(QPalette.ColorRole.Base).name() == theme_color('#22322a', 'Light', 'Ocean')
    assert window.graph_page.view.backgroundBrush().color().name() == theme_color('#f5f6f2', 'Dark', 'Ocean')
    assert theme_color('#1e6554', 'Dark', 'Ocean') in window.styleSheet()
    assert not window.drawer.styleSheet()  # inherits the shared theme
    assert all(not section.button.styleSheet() for section in window.settings_page.sections.values())
    saved = json.loads(Path(config.SETTINGS_PATH).read_text())
    assert saved['qt_theme'] == 'Dark'
    assert saved['qt_color_theme'] == 'Ocean'
    assert saved['unrelated_preference'] == 'preserved'
    window.close()
    reopened = WorkbenchWindow()
    try:
        assert reopened.settings_page.appearance_panel.theme.currentText() == 'Dark'
        assert reopened.graph_page.theme == 'Dark'
        assert reopened.graph_page.color_theme == 'Ocean'
        assert reopened.settings_page.appearance_panel.color_theme.currentText() == 'Ocean'
        reopened.settings_page.appearance_panel.theme.setCurrentText('Light')
        reopened.settings_page.appearance_panel.color_theme.setCurrentText('Forest')
        reopened.settings_page.appearance_panel.apply_settings()
        assert application.palette().color(QPalette.ColorRole.Base).name() == '#ffffff'
        assert reopened.graph_page.view.backgroundBrush().color().name() == '#f5f6f2'
    finally:
        reopened.close()
        reopened.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_logger_catalog_global_reset_persistence_and_startup_levels(workbench):
    application, window = workbench
    panel = window.settings_page.logging_panel
    assert 'core.repo.policy_analysis_repository' in panel.levels
    assert 'mcp_server' in panel.levels
    assert 'dynamic_group_tab' in panel.levels
    assert len(panel.levels) > 50
    runtime = logging.getLogger('qt_test_runtime.child')
    runtime.setLevel(logging.DEBUG)
    panel.refresh_components()
    panel.levels['qt.main'].setCurrentText('DEBUG')
    panel.levels['global'].setCurrentText('WARNING')
    assert all(combo.currentText() == 'WARNING' for combo in panel.levels.values())
    panel.levels['qt.main'].setCurrentText('ERROR')
    panel.apply_levels()
    assert runtime.level == logging.WARNING
    assert logging.getLogger().level == logging.WARNING
    saved = json.loads(Path(config.SETTINGS_PATH).read_text())
    assert saved['global_log_level'] == 'WARNING'
    assert saved['log_levels']['qt.main'] == 'ERROR'
    assert saved['qt_runtime_log_levels']['qt_test_runtime.child'] == 'WARNING'
    window.close()
    reopened = WorkbenchWindow()
    try:
        assert not reopened.verbose
        assert logging.getLogger().level == logging.WARNING
        assert logging.getLogger('oci-policy-analysis.qt.main').level == logging.ERROR
        assert reopened.settings_page.logging_panel.levels['qt.main'].currentText() == 'ERROR'
        reopened.settings_page.load_sample()
        _wait_for_load(application, reopened)
        assert runtime.level == logging.WARNING
    finally:
        reopened.close()
        reopened.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_overview_counts_data_timestamp_and_usage_buttons(workbench, tmp_path):
    application, window = workbench
    snapshot = sample_snapshot()
    snapshot['data_as_of'] = '2026-10-15T10:00:00Z'
    snapshot['policy_statements'].append(
        {
            **snapshot['policy_statements'][0],
            'internal_id': 'invalid-extra',
            'verb': 'unknown-verb',
            'statement_text': 'Retained invalid statement',
        }
    )
    path = tmp_path / 'counts.json'
    path.write_text(json.dumps(snapshot))
    window.controller.start_load('file', {'path': str(path)}, 'Counts test')
    _wait_for_load(application, window)
    page = window.settings_page
    assert page.counts['users'].text() == '0'
    assert page.counts['groups'].text() == '4'
    assert page.counts['dynamic_groups'].text() == '3'
    assert page.counts['policies'].text() == '5'
    assert page.counts['statements'].text() == '7'
    assert page.counts['invalid'].text() == '1'
    assert page.counts['policies'].parentWidget() is page.counts['statements'].parentWidget()
    assert page.counts['invalid'].parentWidget() is page.counts['statements'].parentWidget()
    assert page.counts['users'].parentWidget() is page.counts['groups'].parentWidget()
    assert page.counts['dynamic_groups'].parentWidget() is page.counts['groups'].parentWidget()
    assert page.counts['resource_principal_statements'].text() == '0'
    assert '2026-10-15T10:00:00Z' in window.data_as_of.text()
    assert window.data_as_of.parentWidget() is window.statusBar()
    assert 'Completeness is not guaranteed' not in window.statusBar().currentMessage()
    groups = window.dynamic_groups_page
    groups.in_use.buttons[1].click()
    assert groups.group_table.model.rowCount() == 2
    groups.in_use.buttons[2].click()
    assert groups.group_table.model.rowCount() == 1
    groups.in_use.buttons[0].click()
    assert groups.group_table.model.rowCount() == 3


def test_named_cache_load_uses_worker_and_preserves_source(workbench):
    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    previous = window.controller.context
    previous.cache_service.save_cache(previous.policy_repo, preserved=True)
    window.settings_page.refresh_caches()
    page = window.settings_page
    assert page.cache_button.isEnabled()
    assert page.cache_list.currentText().startswith('(P) ')
    files = {path: path.read_bytes() for path in previous.cache.cache_dir.glob('*.json')}
    page.cache_button.click()
    _wait_for_load(application, window)
    assert window.controller.context is not previous
    assert window.browser_page.model.rowCount() == 6
    assert {path: path.read_bytes() for path in files} == files


def test_cis_load_routes_directory_and_user_option_to_worker(workbench, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    application, window = workbench
    captured = {}

    def load(self, path, **kwargs):
        captured.update(kwargs)
        captured['path'] = path
        captured['thread'] = QThread.currentThread()
        return LoadResult(True, 'CIS test', {})

    monkeypatch.setattr(QFileDialog, 'getExistingDirectory', lambda *args, **kwargs: '/fictional/cis-output')
    monkeypatch.setattr(LoadService, 'load_from_compliance_output', load)
    window.settings_page.cis_users.setChecked(False)
    window.settings_page.cis_button.click()
    _wait_for_load(application, window)
    assert captured['path'] == '/fictional/cis-output'
    assert captured['load_all_users'] is False
    assert captured['post_load_profile'] == 'minimal'
    assert captured['thread'] != application.thread()


def test_embedded_mcp_isolated_contexts_reuse_queries_without_mutating_globals(workbench):
    import asyncio

    pytest.importorskip('fastmcp')
    from fastmcp import Client

    from oci_policy_analysis import mcp_server
    from oci_policy_analysis.application.context import AppContext

    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    loaded = window.controller.context
    empty = AppContext.from_settings({'global_log_level': 'WARNING'})
    standalone = mcp_server.app_context

    async def query():
        first = await mcp_server.create_snapshot_server(loaded)
        second = await mcp_server.create_snapshot_server(empty)
        async with Client(first) as one, Client(second) as two:
            tools = {tool.name for tool in await one.list_tools()}
            assert tools == {
                'snapshot_status',
                'policy_search',
                'policy_search_set',
                'identity_search',
                'cross_tenancy_search',
                'tag_based_policy_search',
                'oke_workload_identity_search',
            }
            status, other = await asyncio.gather(one.call_tool('snapshot_status'), two.call_tool('snapshot_status'))
            assert status.data['statements'] == 6
            assert other.data['statements'] == 0
            result = await one.call_tool(
                'policy_search', {'filters': {'subject_type': ['dynamic-group']}, 'detail_level': 'full'}
            )
            assert not result.is_error
            assert result.data['total_count'] == 2
            assert 'AppWorkers' in json.dumps(result.data)
            empty_result = await two.call_tool('policy_search', {'filters': {'subject_type': ['dynamic-group']}})
            assert empty_result.data['total_count'] == 0
            with pytest.raises(Exception, match='Unknown tool|not found'):
                await one.call_tool('data_operations', {'operation': 'reload'})
        assert mcp_server.app_context is standalone

    asyncio.run(query())


def test_managed_mcp_http_readiness_reload_lock_stop_restart(workbench):
    import asyncio

    pytest.importorskip('fastmcp')
    from fastmcp import Client

    application, window = workbench
    window.experience.set_advanced(True)
    page = window.mcp_page
    assert not page.start_button.isEnabled()
    assert not page.client.active
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    context = window.controller.context
    page.port.setValue(0)
    page.start_button.click()
    assert window.controller.load_block_reason
    assert not window.settings_page.load_button.isEnabled()
    window.controller.start_load('sample', {}, 'Must be blocked')
    assert window.controller.worker is None
    _wait_until(application, lambda: page._running or page.host is None, timeout=25)
    assert page._running, page.server_status.text()
    endpoint = page.url
    assert endpoint.startswith('http://127.0.0.1:')
    assert page.tools.model.rowCount() == 7
    assert window.settings_page.logging_panel.isEnabled()

    async def query():
        async with Client(endpoint) as client:
            result = await client.call_tool('snapshot_status')
            assert result.data['statements'] == 6
            assert result.data['tenancy_name'] == 'Sample workspace'

    asyncio.run(query())
    page.stop_button.click()
    _wait_until(application, lambda: not page.active, timeout=15)
    assert page.server_status.text() == 'Stopped'
    assert not window.controller.load_block_reason
    assert window.settings_page.load_button.isEnabled()
    assert window.controller.context is context
    page.start_button.click()
    _wait_until(application, lambda: page._running or page.host is None, timeout=25)
    assert page._running, page.server_status.text()
    window.show()
    window.close()  # Close completes itself only after server shutdown.
    _wait_until(application, lambda: not page.active and not window.isVisible(), timeout=15)


def test_managed_mcp_occupied_port_recovers_without_false_running_state(workbench):
    import socket

    pytest.importorskip('fastmcp')
    application, window = workbench
    window.experience.set_advanced(True)
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    page = window.mcp_page
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0))
        occupied.listen()
        page.port.setValue(occupied.getsockname()[1])
        page.start_server()
        _wait_until(application, lambda: page.host is None, timeout=20)
        assert not page._running
        assert 'Failed:' in page.server_status.text()
        assert not window.controller.load_block_reason
        assert page.start_button.isEnabled()


def test_codex_configuration_is_child_only_and_disables_unrelated_servers(workbench, tmp_path, monkeypatch):
    from oci_policy_analysis.presentation.qt.codex_client import child_arguments

    codex_dir = tmp_path / '.codex'
    codex_dir.mkdir()
    path = codex_dir / 'config.toml'
    content = (
        '[mcp_servers.other]\nurl="https://example.invalid/mcp"\n[profiles.work.mcp_servers.extra]\ncommand="example"\n'
    )
    path.write_text(content)
    monkeypatch.delenv('CODEX_HOME', raising=False)
    args = child_arguments('http://127.0.0.1:12345/mcp', 'test_snapshot')
    import tomllib

    table = next(arg for arg in args if arg.startswith('mcp_servers='))
    configured = tomllib.loads(table)['mcp_servers']
    assert set(configured) == {'test_snapshot', 'other', 'extra'}
    assert configured['other']['enabled'] is False
    assert configured['extra']['enabled'] is False
    assert configured['test_snapshot']['url'] == 'http://127.0.0.1:12345/mcp'
    assert configured['test_snapshot']['enabled'] is True
    assert '--disable' in args and 'shell_tool' in args
    assert 'apps' in args and 'browser_use' in args
    assert path.read_text() == content
    with pytest.raises(ValueError):
        child_arguments('https://external.example/mcp', 'test')


def test_codex_process_handshake_stream_failure_and_interrupt_without_model_requests(workbench, monkeypatch, tmp_path):
    import sys

    application, window = workbench
    page = window.mcp_page
    client = page.client
    stub = tmp_path / 'app_server_stub.py'
    requests = tmp_path / 'rpc.jsonl'
    stub.write_text("""import json, sys, time
name, url, log = sys.argv[1:]
turn_number = 0

def send(value):
    sys.stdout.write(json.dumps(value, ensure_ascii=False) + "\\n")
    sys.stdout.flush()

for line in sys.stdin:
    request = json.loads(line)
    with open(log, "a") as output:
        output.write(json.dumps(request) + "\\n")
    method = request.get("method")
    if "id" not in request:
        continue
    result = {}
    if method == "config/read":
        result = {"config": {"mcp_servers": {name: {"enabled": True, "url": url}}}}
    elif method == "account/read":
        result = {"account": {"type": "apiKey"}, "requiresOpenaiAuth": True}
    elif method == "model/list":
        result = {"data": [{"id": "test-model", "model": "test-model", "displayName": "Protocol test model", "isDefault": True}], "nextCursor": None}
    elif method == "thread/start":
        result = {"thread": {"id": "fake-thread"}}
    elif method == "mcpServerStatus/list":
        result = {"data": [{"name": name, "tools": {"snapshot_status": {}, "policy_search": {}}}], "nextCursor": None}
    elif method == "turn/start":
        turn_number += 1
        result = {"turn": {"id": f"turn-{turn_number}"}}
    send({"id": request["id"], "result": result})
    if method == "turn/start":
        send({"method": "turn/started", "params": {"threadId": "fake-thread", "turn": {"id": f"turn-{turn_number}"}}})
        if turn_number == 1:
            send({"method": "item/started", "params": {"threadId": "fake-thread", "item": {"type": "mcpToolCall", "tool": "policy_search", "status": "inProgress"}}})
            payload = (json.dumps({"method": "item/agentMessage/delta", "params": {"threadId": "fake-thread", "itemId": "answer", "delta": "AppWorkers → fictional policy evidence"}}, ensure_ascii=False) + "\\n").encode()
            cut = payload.index("→".encode()) + 1
            sys.stdout.buffer.write(payload[:cut]); sys.stdout.buffer.flush()
            time.sleep(.02)
            sys.stdout.buffer.write(payload[cut:]); sys.stdout.buffer.flush()
        if turn_number < 3:
            send({"method": "turn/completed", "params": {"threadId": "fake-thread", "turn": {"id": f"turn-{turn_number}", "status": "completed" if turn_number == 1 else "failed", "error": None if turn_number == 1 else {"message": "Synthetic failure"}}}})
    elif method == "turn/interrupt":
        send({"method": "turn/completed", "params": {"threadId": "fake-thread", "turn": {"id": f"turn-{turn_number}", "status": "interrupted"}}})
""")
    original = client.process.setArguments
    launch_args = []

    def arguments(args):
        launch_args.extend(args)
        original([str(stub), client.server_name, client.url, str(requests)])

    monkeypatch.setattr(client.process, 'setArguments', arguments)
    client.start('http://127.0.0.1:12345/mcp', sys.executable)
    _wait_until(application, lambda: client.ready, timeout=10)
    assert page.model.currentData() == 'test-model'
    assert launch_args[:3] == ['app-server', '--listen', 'stdio://']
    assert 'turn/start' not in requests.read_text()
    scratch = Path(client._scratch.name)
    client.send('Find fictional AppWorkers evidence', 'test-model')
    _wait_until(application, lambda: client.ready and not client.busy)
    page._flush_text()
    assert 'AppWorkers → fictional policy evidence' in page.conversation.toPlainText()
    assert 'policy_search' in page.events.toPlainText()
    messages = [json.loads(line) for line in requests.read_text().splitlines()]
    methods = [message.get('method') for message in messages]
    assert methods.index('mcpServerStatus/list') < methods.index('turn/start')
    thread = next(message for message in messages if message.get('method') == 'thread/start')
    assert thread['params']['sandbox'] == 'read-only'
    assert thread['params']['ephemeral'] is True
    client.send('Synthetic failure', 'test-model')
    _wait_until(application, lambda: client.ready and not client.busy)
    assert 'failed' in page.assistant_status.text()
    assert 'Synthetic failure' in page.assistant_status.text()
    client.send('Wait for interruption', 'test-model')
    _wait_until(application, lambda: client.turn_id is not None)
    client.interrupt()
    _wait_until(application, lambda: not client.busy)
    assert 'interrupted' in page.assistant_status.text()
    client.stop()
    _wait_until(application, lambda: not client.active)
    assert not scratch.exists()
    assert page.assistant_status.text() == 'Codex disconnected'


def test_codex_rejects_unknown_configuration_permissions_malformed_data_and_timeouts(workbench, monkeypatch):
    from oci_policy_analysis.presentation.qt.codex_client import CodexClient

    _, window = workbench
    client = CodexClient(window)
    messages, statuses = [], []
    monkeypatch.setattr(client, '_write', messages.append)
    client.status.connect(statuses.append)
    client.receive(
        json.dumps(
            {
                'id': 'approval',
                'method': 'item/commandExecution/requestApproval',
                'params': {'command': 'synthetic command'},
            }
        ).encode()
        + b'\n'
    )
    assert messages[-1] == {'id': 'approval', 'result': {'decision': 'decline'}}
    client.server_name = 'target'
    client.url = 'http://127.0.0.1:12345/mcp'
    client._configuration({'config': {'mcp_servers': {'target': {'url': client.url}, 'unrelated': {'enabled': True}}}})
    assert 'Unrelated MCP' in statuses[-1]
    assert not client.ready
    assert not any(message.get('method') == 'turn/start' for message in messages)
    another = CodexClient(window)
    another.status.connect(statuses.append)
    another.receive(b'{invalid json}\n')
    assert 'malformed' in statuses[-1]
    another = CodexClient(window)
    another.status.connect(statuses.append)
    another.request('initialize', {}, lambda _: None, timeout=-1)
    another._timeouts()
    assert 'timed out' in statuses[-1]
    assert not another.ready


def test_codex_missing_executable_and_absent_account_are_recoverable(workbench):
    _, window = workbench
    client = window.mcp_page.client
    statuses = []
    client.status.connect(statuses.append)
    client.start('http://127.0.0.1:12345/mcp', '/nonexistent/opa-codex-binary')
    assert not client.active
    assert 'not found' in statuses[-1]
    client._account({'account': None, 'requiresOpenaiAuth': True})
    assert 'codex login' in statuses[-1]
    assert not client.ready


def test_mcp_cannot_start_during_a_replacement_load(workbench, monkeypatch):
    application, window = workbench
    window.experience.set_advanced(True)
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    entered, release = threading.Event(), threading.Event()

    def load(self, **kwargs):
        entered.set()
        if not release.wait(5):
            raise RuntimeError('test timed out')
        return LoadResult(True, 'Replacement test', {})

    monkeypatch.setattr(LoadService, 'load_from_tenancy', load)
    window.settings_page.load_button.click()
    try:
        _wait_until(application, entered.is_set)
        assert not window.mcp_page.start_button.isEnabled()
        window.mcp_page.start_server()
        assert window.mcp_page.host is None
    finally:
        release.set()
        _wait_for_load(application, window)
    assert window.mcp_page.start_button.isEnabled()


def test_codex_discovery_distinguishes_disabled_metadata_from_active_connectors(workbench, monkeypatch):
    from oci_policy_analysis.presentation.qt.codex_client import CodexClient

    _, window = workbench
    client = CodexClient(window)
    client.server_name = 'snapshot'
    client.thread_id = 'synthetic-thread'
    client._disabled_servers = {'legacy'}
    client._question = 'Synthetic question'
    client.busy = True
    sent, statuses = [], []
    monkeypatch.setattr(client, '_write', sent.append)
    client.status.connect(statuses.append)
    target = {'name': 'snapshot', 'runtimeStatus': 'connected', 'tools': {'snapshot_status': {}, 'policy_search': {}}}
    client._tools_ready({'data': [target, {'name': 'legacy', 'runtimeStatus': 'disabled', 'tools': {}}]})
    assert any(message.get('method') == 'turn/start' for message in sent)
    sent.clear()
    client._tools_ready({'data': [target, {'name': 'codex_apps', 'runtimeStatus': 'starting', 'tools': {'other': {}}}]})
    assert not any(message.get('method') == 'turn/start' for message in sent)
    assert 'unrelated MCP servers' in statuses[-1]
    assert not client.ready


def test_navigation_never_scrolls_horizontally_and_logs_only_open_on_request(workbench):
    from PySide6.QtCore import Qt

    application, window = workbench
    assert window.navigation.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    appearance = window.settings_page.appearance_panel
    assert appearance.theme.minimumWidth() == 175
    assert appearance.color_theme.minimumWidth() == 175
    assert appearance.font_size.minimumWidth() == 175
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    assert window.log_dock.isHidden()
    window.settings_page.show_log.click()
    assert not window.log_dock.isHidden()
    window.log_dock.hide()
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    assert window.log_dock.isHidden()


def test_resource_principal_statistic_is_source_statement_evidence_not_unique_resources(workbench):
    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    context = window.controller.context
    template = context.policy_repo.regular_statements[0]
    # Two statements can refer to the same broad subject; count statements, not a
    # made-up number of distinct workload identities. Include retained invalid evidence.
    context.policy_repo.regular_statements.extend(
        [
            {**template, 'internal_id': 'broad-1', 'subject_type': 'any-user'},
            {**template, 'internal_id': 'broad-2', 'subject_type': 'ANY-USER'},
            {**template, 'internal_id': 'broad-3', 'subject_type': 'any-group', 'valid': False},
        ]
    )
    window.settings_page.set_snapshot(context, LoadResult(True, 'Count evidence', {}), 'Count evidence')
    count = window.settings_page.counts['resource_principal_statements']
    assert count.text() == '3'
    assert 'not a count of distinct' in count.parentWidget().toolTip()
    assert window.settings_page.counts['invalid'].text() == '1'


def test_navigation_requires_snapshot_except_overview_and_tools(workbench, tmp_path):
    from PySide6.QtCore import Qt

    application, window = workbench
    assert window.navigation.item(window.page_index('overview')).flags() & Qt.ItemFlag.ItemIsEnabled
    for index in range(1, window.navigation.count()):
        assert bool(window.navigation.item(index).flags() & Qt.ItemFlag.ItemIsEnabled) == (
            index == window.page_index('tools')
        )
        assert window.pages.widget(index).isEnabled() == (index == window.page_index('tools'))
        window.navigation.setCurrentRow(index)
        assert window.pages.currentIndex() == (window.page_index('tools') if index == window.page_index('tools') else 0)
    window.controller.start_load('file', {'path': str(tmp_path / 'absent.json')}, 'Missing snapshot')
    _wait_for_load(application, window)
    assert not window.navigation.item(window.page_index('resource_principals')).flags() & Qt.ItemFlag.ItemIsEnabled
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    for index in range(1, window.navigation.count()):
        if window.navigation.item(index).isHidden():
            continue
        assert window.navigation.item(index).flags() & Qt.ItemFlag.ItemIsEnabled
        assert window.pages.widget(index).isEnabled()
    window.navigation.setCurrentRow(window.page_index('resource_principals'))
    previous = window.resource_principals_page.context
    window.controller.start_load('file', {'path': str(tmp_path / 'absent.json')}, 'Failed reload')
    _wait_for_load(application, window)
    assert window.resource_principals_page.context is previous
    assert window.navigation.item(window.page_index('resource_principals')).flags() & Qt.ItemFlag.ItemIsEnabled
    assert window.pages.currentIndex() == window.page_index('resource_principals')


def test_expanded_sample_resource_principal_workflows(workbench, monkeypatch):
    import re

    from PySide6.QtCore import QItemSelectionModel

    from oci_policy_analysis.presentation.qt.sample_data import sample_snapshot as expanded_sample

    application, window = workbench
    snapshot = expanded_sample()
    serialized = json.dumps(snapshot)
    assert {key: len(snapshot[key]) for key in ('groups', 'users', 'policies', 'compartments')} == {
        'groups': 25,
        'users': 50,
        'policies': 100,
        'compartments': 22,
    }
    assert all(
        re.fullmatch(r'ocid1\.\w+\.oc1\.\.sample\d+', value)
        for value in re.findall(r'ocid1\.[A-Za-z0-9.]+', serialized)
    )
    known_groups = {group['group_ocid'] for group in snapshot['groups']}
    assert all(1 <= len(user['groups']) <= 4 and set(user['groups']) <= known_groups for user in snapshot['users'])
    assert {len(user['groups']) for user in snapshot['users']} == {1, 2, 3, 4}
    assert all(user['email'].endswith('@example.invalid') for user in snapshot['users'])
    snapshot['groups'].clear()
    assert len(expanded_sample()['groups']) == 25
    monkeypatch.setattr('oci_policy_analysis.presentation.qt.loading.sample_snapshot', expanded_sample)
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    assert window.browser_page.model.rowCount() == 325
    window.show()
    window.resize(1100, 760)
    application.processEvents()
    assert window.settings_page.load_button.height() >= 30
    assert window.settings_page.verticalScrollBar().maximum() > 0
    assert window.settings_page.counts['users'].text() == '50'
    assert window.settings_page.counts['invalid'].text() == '3'
    from oci_policy_analysis.application.services.principal_analysis_service import PrincipalAnalysisService

    assert (
        PrincipalAnalysisService(window.controller.context)
        .by_groups_users(users=[window.controller.context.policy_repo.users[0]])
        .statements
    )
    page = window.resource_principals_page
    window.navigation.setCurrentRow(window.page_index('resource_principals'))
    assert page.context is window.controller.context
    assert page.statements.model.rowCount() >= 24
    page.mode.setCurrentText('any-group')
    assert page.statements.model.rowCount() == 4
    page.mode.setCurrentText('any-user')
    assert page.statements.model.rowCount() > 0
    assert all(row['subject_type'] == 'any-user' for row in page.statements.model.records)
    page.mode.setCurrentIndex(0)
    page.resource_type.setCurrentText('fnfunc')
    assert page.statements.model.rowCount() > 0
    assert all('fnfunc' in row['conditions'] for row in page.statements.model.records)
    page.compartment.setText('ocid1.compartment.oc1..sample0002')
    _wait_until(application, lambda: not page.timer.isActive())
    assert page.statements.model.rowCount() > 0
    page.statements.selectRow(0)
    assert window.drawer.record is None
    menu = page.statements.context_menu(page.statements.selected_records()[0])
    menu.actions()[0].trigger()
    menu.deleteLater()
    assert 'fnfunc' in window.drawer.raw.toPlainText()
    page.mode.setCurrentText('OKE Workload Identity')
    assert window.drawer.record is None
    assert page.statements.model.rowCount() >= 12
    page.oke['namespaces'].setCurrentText('payments')
    page.oke['service_accounts'].setCurrentText('reader')
    _wait_until(application, lambda: not page.timer.isActive())
    assert page.statements.model.rowCount() > 0
    assert all(
        'payments' in row['conditions'] and 'reader' in row['conditions'] for row in page.statements.model.records
    )
    page.oke['namespaces'].setCurrentText('no-such-namespace')
    _wait_until(application, lambda: not page.timer.isActive())
    assert page.statements.model.rowCount() == 0
    page.mode.setCurrentText('Dynamic Group')
    assert page.statements.model.rowCount() == 0
    selection = page.groups.selectionModel()
    for i in range(2):
        selection.select(
            page.groups.proxy.index(i, 0),
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )
    assert len(page.groups.selected_records()) == 2
    assert page.statements.model.rowCount() > 0
    statement = page.statements.model.records[0]
    menu = page.statements.context_menu(statement)
    menu.actions()[1].trigger()
    menu.deleteLater()
    assert window.pages.currentIndex() == window.page_index('dynamic_groups')
    assert window.dynamic_groups_page.group_table.selected_records()
    page.group_search.setText('no-such-group')
    assert page.statements.model.rowCount() == 0
    page.reset_filters()
    assert page.mode.currentIndex() == 0
    assert page.statements.model.rowCount() >= 24
    assert not window.log_dock.isVisible()


def test_advanced_mode_is_central_saved_and_tools_share_logging(workbench, monkeypatch):
    from oci_policy_analysis.presentation.qt.preferences import load_preferences

    application, window = workbench
    assert not window.experience.advanced
    assert not window.navigation.item(window.page_index('recommendations')).isHidden()  # Recommendations are standard.
    assert all(
        window.navigation.item(index).isHidden()
        for index in [window.page_index(key) for key in ('mcp', 'prospective', 'simulation', 'consolidation')]
    )
    assert not window.tools_page.isTabVisible(2)
    changes = []
    window.experience.changed.connect(changes.append)
    window.settings_page.advanced_mode.setChecked(True)
    assert changes == [True]
    assert load_preferences()['qt_advanced_mode'] is True
    assert all(
        not window.navigation.item(index).isHidden()
        for index in [window.page_index(key) for key in ('mcp', 'prospective', 'simulation', 'consolidation')]
    )
    assert window.tools_page.isTabVisible(2)
    # Mode changes do not unlock pages until data is loaded.
    window.navigation.setCurrentRow(window.page_index('simulation'))
    assert window.pages.currentIndex() == window.page_index('overview')
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    previous = window.controller.context
    window.navigation.setCurrentRow(window.page_index('simulation'))
    assert window.pages.currentWidget() is window.simulation_page
    window.settings_page.advanced_mode.setChecked(False)
    assert window.pages.currentIndex() == window.page_index('overview')
    assert window.controller.context is previous
    assert load_preferences()['qt_advanced_mode'] is False
    window.navigation.setCurrentRow(window.page_index('tools'))
    window.tools_page.show_logs.emit()
    assert not window.log_dock.isHidden()
    window.tools_page.show_logging_settings.emit()
    assert window.pages.currentIndex() == window.page_index('overview')
    assert window.settings_page.sections['Logging'].button.isChecked()

    # A failed preference write must not break the live mode or change data.
    def unavailable(*_args):
        raise OSError('Read only')

    monkeypatch.setattr('oci_policy_analysis.presentation.qt.experience.save_preferences', unavailable)
    window.experience.set_advanced(True)
    assert window.experience.advanced
    assert 'session' in window.settings_page.mode_status.text()
    assert window.controller.context is previous


def test_checked_table_native_inclusion_survives_proxy_and_scopes_bulk_actions(workbench):
    from copy import deepcopy

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from oci_policy_analysis.presentation.qt.selection_table import CheckedRecordTable

    application, window = workbench
    rows = [
        {'internal_id': 'a', 'name': 'Alpha', 'checkable': True},
        {'internal_id': 'b', 'name': 'Beta', 'checkable': True},
        {'internal_id': 'c', 'name': 'Closed', 'checkable': False, 'selection_reason': 'Protected statement'},
        {'name': 'Missing stable ID'},
    ]
    original = deepcopy(rows)
    widget = CheckedRecordTable((('Name', 'name'),), key=lambda row: row.get('internal_id', ''))
    widget.model.replace(rows)
    widget.show()
    application.processEvents()
    model, table = widget.model, widget.table
    assert model.data(model.index(2, 0), Qt.ItemDataRole.ToolTipRole) == 'Protected statement'
    assert not model.setData(model.index(2, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert not model.setData(model.index(3, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    index = table.proxy.mapFromSource(model.index(1, 0))
    table.setCurrentIndex(index)
    QTest.keyClick(table, Qt.Key.Key_Space)
    assert model.checked_ids() == ['b']
    table.proxy.setFilterFixedString('Alpha')
    widget._visible(True)
    assert model.checked_ids() == ['a', 'b']
    assert '1 checked outside filter' in widget.counts.text()
    widget._visible(False)
    assert model.checked_ids() == ['b']
    received = []
    action = widget.add_checked_action('Use checked IDs', received.append)
    action.click()
    assert received == [['b']]
    assert rows == original
    model.replace(rows, preserve_checks=True)
    assert model.checked_ids() == ['b']
    with pytest.raises(ValueError, match='unique'):
        model.replace([rows[0], rows[0]])
    assert model.checked_ids() == ['b']  # Failed replacement is atomic.
    model.replace(rows)
    assert model.checked_ids() == []
    assert not action.isEnabled()
    widget.close()
    widget.deleteLater()
    application.processEvents()


def test_checked_table_supports_core_workflow_row_contracts(workbench):
    from oci_policy_analysis.application.services.consolidation_workbench_service import ConsolidationWorkbenchService
    from oci_policy_analysis.application.services.recommendations_service import RecommendationsService
    from oci_policy_analysis.application.services.simulation_service import SimulationService
    from oci_policy_analysis.presentation.qt.selection_table import CheckedRecordTable

    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    context = window.controller.context
    consolidation = ConsolidationWorkbenchService(context)
    candidates = consolidation.get_candidate_rows()['rows']
    assert candidates
    widget = CheckedRecordTable((('Statement', 'statement_text'),), key=lambda row: row.get('internal_id', ''))
    widget.model.replace(candidates)
    widget._visible(True)
    assert widget.model.checked_ids() == [row['internal_id'] for row in candidates]
    preparation = SimulationService(context).prepare(
        compartment_path='ROOT/Applications', principal_type='dynamic-group', principal=('Default', 'AppWorkers')
    )
    assert preparation.principal_key
    widget.model.replace(consolidation.get_protection_rows())
    assert widget.model.checked_ids() == []
    # Recommendation risk rows intentionally have no action IDs today. They can
    # still be inspected; a UI must not fabricate row-position operation IDs.
    risk_rows = RecommendationsService(context).get_dashboard_payload()['risk_statement']
    assert risk_rows
    widget.model.replace(risk_rows)
    widget._visible(True)
    assert widget.model.checked_ids() == []
    assert widget.model.rowCount() == len(risk_rows)
    widget.deleteLater()
    application.processEvents()


def test_prospective_modal_save_visibility_risk_and_delete(workbench, monkeypatch):
    from copy import deepcopy

    from PySide6.QtWidgets import QDialog

    from oci_policy_analysis.presentation.qt.pages.prospective import ProspectiveEditorDialog

    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    context = window.controller.context
    source = deepcopy(context.policy_repo.regular_statements)
    overlay = deepcopy(context.intelligence.overlay)
    window.experience.set_advanced(True)
    page = window.prospective_page

    def fill_dialog(dialog):
        assert dialog.metadata['principals']
        assert 'dynamic-group:operations/appworkers' in dialog.metadata['principals']
        dialog.description.setText('New test prospect')
        dialog.statement.setPlainText('Allow group Developers to read buckets in tenancy')
        dialog._validate()
        assert 'Parsed and valid' in dialog.validation.text()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ProspectiveEditorDialog, 'exec', fill_dialog)
    page._add()
    assert 'Saved for this tenancy' in page.status.text()
    assert page.table.model.rowCount() == 1
    assert window.browser_page.model.rowCount() == 7
    assert len(context.simulation.get_prospective_statements()) == 1
    assert any(grant['prospective'] for grant in window.graph_page.result['grants'])
    page.table.selectRow(0)
    assert 'Potential risk estimate:' in page.detail.toPlainText()
    assert context.policy_repo.regular_statements == source
    assert context.intelligence.overlay == overlay
    assert any(
        row.get('is_prospective')
        for row in context.simulation.get_applicable_statements('group:default/developers', 'ROOT')
    )
    window.experience.set_advanced(False)
    assert window.browser_page.model.rowCount() == 6
    assert not any(grant['prospective'] for grant in window.graph_page.result['grants'])
    assert 'prospective' not in window.browser_page.row_label.text()
    assert not window.drawer.record
    window.experience.set_advanced(True)
    window.browser_page.filters['statement_text'].setText('Developers')
    window.browser_page.apply_filters()
    assert any(row['is_prospective'] for row in window.browser_page.model.records if row.get('is_prospective'))
    page._delete()
    assert page.table.model.rowCount() == 0
    assert context.simulation.get_prospective_statements() == []


def test_prospective_draft_cancel_invalid_and_save_failure(workbench, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from oci_policy_analysis.presentation.qt.pages.prospective import ProspectiveEditorDialog

    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    page = window.prospective_page
    context = window.controller.context
    dialog = ProspectiveEditorDialog(context)
    dialog._accept_draft()
    assert dialog.result() != QDialog.DialogCode.Accepted
    dialog.fields['principal_key'].setCurrentIndex(0)
    dialog._use_generated()
    assert dialog.statement.toPlainText() == dialog.preview.toPlainText()
    dialog.reject()
    dialog.deleteLater()
    assert page.service.records.list_all() == []

    def invalid(dialog):
        dialog.statement.setPlainText('This is not a policy')
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ProspectiveEditorDialog, 'exec', invalid)
    page._add()
    assert page.table.model.rowCount() == 1
    assert not page.service.records.list_all()[0].valid
    assert not page.service.potential_risk(page.service.records.list_all()[0])
    window.experience.set_advanced(True)
    assert any(row.get('is_prospective') and not row['valid'] for row in window.browser_page.model.records)
    assert not any(grant['prospective'] for grant in window.graph_page.result['grants'])

    def fail(*_args):
        raise OSError('disk unavailable')

    monkeypatch.setattr(context.cache, 'save_prospects', fail)
    page._add()
    assert page.table.model.rowCount() == 1
    assert len(page.service.records.list_all()) == 1
    assert 'Could not save: disk unavailable' in page.status.text()


def test_prospective_reload_and_tenancy_isolation(workbench):
    from oci_policy_analysis.application.services.prospective_workbench_service import ProspectiveWorkbenchService

    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    context = window.controller.context
    service = window.prospective_page.service.records
    service.append_from_simple_dict({'statement_text': 'Allow group Developers to read buckets in tenancy'})
    service.persist_and_push_to_engine(strict=True)
    del context._prospective_service
    rebound = ProspectiveWorkbenchService(context)
    assert len(rebound.records.list_all()) == 1
    assert len(context.simulation.get_prospective_statements()) == 1
    context.policy_repo.tenancy_ocid = 'ocid1.tenancy.oc1..other-test'
    other = ProspectiveWorkbenchService(context)
    assert other.records.list_all() == []
    assert context.simulation.get_prospective_statements() == []
    assert not other.statement_views()


def test_condition_tester_without_tenancy_rhs_null_and_stale_inputs(workbench):
    application, window = workbench
    window.navigation.setCurrentRow(window.page_index('tools'))
    assert window.pages.currentWidget() is window.tools_page
    page = window.tools_page.condition_tester
    page.set_clause_text('request.principal.id = target.bucket.owner.id')
    assert set(page.input_widgets) == {'request.principal.id', 'target.bucket.owner.id'}
    assert page.evaluate_button.isEnabled()
    for value, _null in page.input_widgets.values():
        value.setText('alice')
    page.evaluate()
    assert page.result.text() == 'Condition matched'
    assert page.comparisons.model.rowCount() == 1
    assert 'alice' in page.raw_result.toPlainText()
    page.input_widgets['target.bucket.owner.id'][1].setChecked(True)
    assert not page.input_widgets['target.bucket.owner.id'][0].isEnabled()
    assert page.comparisons.model.rowCount() == 0
    page.evaluate()
    assert page.result.text() == 'Condition did not match'
    assert 'Missing right-hand variable' in page.raw_result.toPlainText()
    page.clause.setPlainText('!request.principal.type')
    assert not page.evaluate_button.isEnabled()
    assert page.raw_result.toPlainText() == ''
    page.parse_clause()
    page.evaluate()
    assert page.result.text() == 'Condition matched'
    page.input_widgets['request.principal.type'][0].setText('workload')
    page.evaluate()
    assert page.result.text() == 'Condition did not match'
    page.set_clause_text("request.a = 'x' @")
    assert not page.evaluate_button.isEnabled()
    assert page.input_widgets == {}
    assert 'Cannot test:' in page.status.text()
    page._clear()
    assert page.clause.toPlainText() == ''


@pytest.mark.parametrize('table_name', ['browser', 'graph', 'dynamic', 'resource', 'prospective'])
def test_condition_tester_handoffs_from_statement_tables(workbench, table_name):
    application, window = workbench
    tables = {
        'browser': window.browser_page.table,
        'graph': window.graph_page.statements,
        'dynamic': window.dynamic_groups_page.statements,
        'resource': window.resource_principals_page.statements,
        'prospective': window.prospective_page.table,
    }
    table = tables[table_name]
    page = window.tools_page.condition_tester
    page.set_clause_text("request.old = 'x'")
    page.input_widgets['request.old'][0].setText('old private value')
    statement = "Allow group 'where' to read buckets in tenancy where any { !request.a, request.a = target.b }"
    menu = table.context_menu({'statement_text': statement})
    next(action for action in menu.actions() if action.text() == 'Test condition…').trigger()
    menu.deleteLater()
    assert window.pages.currentWidget() is window.tools_page
    assert window.tools_page.currentIndex() == 0
    assert page.parsed['variables'] == ['request.a', 'target.b']
    assert all(value.text() == '' for value, _null in page.input_widgets.values())
    assert page.raw_result.toPlainText() == ''
    menu = table.context_menu({'statement_text': 'Allow group Readers to read buckets in tenancy'})
    assert not any(action.text() == 'Test condition…' for action in menu.actions())
    menu.deleteLater()


def test_users_groups_inventory_memberships_policies_and_reload(workbench, monkeypatch):
    from copy import deepcopy

    from PySide6.QtCore import QItemSelectionModel, Qt
    from PySide6.QtWidgets import QAbstractItemView

    from oci_policy_analysis.application.services.principal_analysis_service import PrincipalAnalysisService
    from oci_policy_analysis.presentation.qt.sample_data import sample_snapshot as expanded_sample

    application, window = workbench
    page = window.users_groups_page
    page_index = next(i for i, spec in enumerate(window.page_specs) if spec[0] == 'users_groups')
    assert not window.navigation.item(page_index).flags() & Qt.ItemFlag.ItemIsEnabled
    monkeypatch.setattr('oci_policy_analysis.presentation.qt.loading.sample_snapshot', expanded_sample)
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    context = window.controller.context
    original = deepcopy(context.policy_repo.users)
    window.navigation.setCurrentRow(page_index)
    assert window.pages.currentWidget() is page
    assert [page.tabs.tabText(i) for i in range(2)] == ['Group-based View', 'User-based View']
    user_view, group_view = page.user_view, page.group_view
    assert user_view.inventory.model.rowCount() == 50
    assert group_view.inventory.model.rowCount() == 25
    assert user_view.statements.model.rowCount() == 0
    assert user_view.memberships.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    page.tabs.setCurrentIndex(1)
    user_view.inventory.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    selection = user_view.inventory.selectionModel()
    for row in range(2):
        selection.select(
            user_view.inventory.proxy.index(row, 0),
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )
    selected = user_view.inventory.selected_records()
    assert len(selected) == 2
    assert user_view.memberships.model.records == PrincipalAnalysisService(context).user_group_rows(selected)
    assert {row['user_name'] for row in user_view.memberships.model.records} == {user['user_name'] for user in selected}
    assert (
        user_view.statements.model.records
        == PrincipalAnalysisService(context).by_groups_users(users=selected).statements
    )
    assert user_view.statements.model.rowCount() > 0
    assert window.drawer.record is None
    menu = user_view.memberships.context_menu(user_view.memberships.model.records[0])
    menu.actions()[0].trigger()
    menu.deleteLater()
    assert window.drawer.record['user_name'] in {user['user_name'] for user in selected}
    menu = user_view.statements.context_menu(user_view.statements.model.records[0])
    menu.actions()[0].trigger()
    menu.deleteLater()
    assert window.drawer.record['statement_text']
    user_view.search.setText('no such statement')
    assert user_view.statements.proxy.rowCount() == 0
    user_view.search.clear()
    user_view.apply_filters()
    assert len(user_view.inventory.selected_records()) == 2
    user_view.filters['search'].setText('no such user')
    user_view.apply_filters()
    assert user_view.inventory.model.rowCount() == 0
    assert user_view.memberships.model.rowCount() == user_view.statements.model.rowCount() == 0
    assert window.drawer.record is None
    user_view.reset_filters()
    assert user_view.inventory.model.rowCount() == 50
    assert user_view.statements.model.rowCount() == 0
    page.tabs.setCurrentIndex(0)
    group_view.inventory.selectRow(0)
    group = group_view.inventory.selected_records()[0]
    assert group_view.memberships.model.records == context.policy_repo.get_users_for_group(group)
    assert (
        group_view.statements.model.records
        == PrincipalAnalysisService(context).by_groups_users(groups=[group]).statements
    )
    assert context.policy_repo.users == original
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    assert page.context is window.controller.context
    assert page.context is not context
    assert group_view.statements.model.rowCount() == user_view.statements.model.rowCount() == 0
    assert not group_view.inventory.selected_records()


def test_browser_subject_union_detail_filter_order_and_hidden_column(workbench):
    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    page = window.browser_page
    window.navigation.setCurrentRow(window.page_index('browser'))
    window.show()
    application.processEvents()
    assert page.filter_toggle.text() == 'Detailed Filters'
    assert page.search.mapTo(page, page.search.rect().topLeft()).y() < page.filter_toggle.y()
    assert page.table.isColumnHidden(2)
    assert {row['subject_type'] for row in page.model.records} == {'group', 'dynamic-group'}
    page.subject_types.checks['group'].setChecked(True)
    assert page.model.rowCount() == 4
    page.subject_types.checks['dynamic-group'].setChecked(True)
    assert page.model.rowCount() == 6
    page.filters['statement_text'].setText('AppWorkers')
    page.apply_filters()
    assert page.model.rowCount() == 1
    assert page.model.records[0]['subject_type'] == 'dynamic-group'
    page.reset_filters()
    assert not page.subject_types.selected_values()
    assert page.model.rowCount() == 6


def test_navigation_access_headers_and_extra_large_fixed_font(workbench):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontInfo, QFontMetrics
    from PySide6.QtWidgets import QTableView

    from oci_policy_analysis.presentation.qt.preferences import load_preferences

    application, window = workbench
    keys = [spec[0] for spec in window.page_specs]
    assert keys.index('users_groups') + 1 == keys.index('dynamic_groups')
    assert keys.index('recommendations') + 1 == keys.index('mcp')
    assert window.navigation.item(window.page_index('mcp')).isHidden()
    window.experience.set_advanced(True)
    assert not window.navigation.item(window.page_index('mcp')).isHidden()
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    window.navigation.setCurrentRow(window.page_index('mcp'))
    window.experience.set_advanced(False)
    assert window.pages.currentWidget() is window.settings_page
    panel = window.settings_page.appearance_panel
    panel.font_size.setCurrentText('Extra Large')
    panel.fixed_width.setChecked(True)
    panel.compact.setChecked(True)
    panel.apply_settings()
    window.resize(1100, 760)
    window.show()
    for _ in range(5):
        application.processEvents()
    assert load_preferences()['font_size'] == 'Extra Large'
    assert load_preferences()['qt_fixed_width_font'] is True
    for table in window.findChildren(QTableView):
        assert table.horizontalHeader().defaultAlignment() & Qt.AlignmentFlag.AlignLeft
        assert QFontInfo(table.font()).fixedPitch()
        assert table.verticalHeader().defaultSectionSize() >= QFontMetrics(table.font()).height() + 8
    assert window.settings_page.widget().width() <= window.settings_page.viewport().width()
    assert QFontInfo(window.settings_page.load_button.font()).fixedPitch()
    for name in ('Look and Feel', 'Intelligence', 'Logging'):
        section = window.settings_page.sections[name]
        section.button.setChecked(True)
        for _ in range(5):
            application.processEvents()
        assert window.settings_page.widget().width() <= window.settings_page.viewport().width()
        section.button.setChecked(False)
    window.resize(1920, 1080)
    for _ in range(5):
        application.processEvents()
    window.drawer.show_record({'statement_text': 'Allow group Builders to read buckets in tenancy'})
    assert 580 < window.drawer.width() <= 720


def _wait_for_reports(application, window):
    _wait_until(application, lambda: window.tools_page.reports.worker is None)


def test_reports_generate_only_on_request_preview_and_export(workbench, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    from oci_policy_analysis.application.services.reports_service import ReportsService

    application, window = workbench
    page = window.tools_page.reports
    assert not page.run_button.isEnabled()
    original = ReportsService.get_report
    calls = []

    def generate(service, report_id):
        calls.append((report_id, QThread.currentThread() is application.thread()))
        return original(service, report_id)

    monkeypatch.setattr(ReportsService, 'get_report', generate)
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    assert page.report is None and calls == []
    page.run_button.click()
    _wait_for_reports(application, window)
    assert calls == [('policy-inventory', False)]
    assert page.report['counts']['statements'] == len(window.controller.context.policy_repo.regular_statements)
    assert json.loads(page.text_preview.toPlainText()) == page.report
    assert page.export_button.isEnabled()
    for key, extension in [('json', 'json'), ('markdown', 'md'), ('html', 'html')]:
        index = page.format_choice.findData(key)
        page.format_choice.setCurrentIndex(index)
        destination = tmp_path / f'report.{extension}'
        monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, path=destination, **k: (str(path), ''))
        page.export_button.click()
        assert destination.read_text() == page.formats[key]
    assert calls == [('policy-inventory', False)]
    assert page.previews.currentWidget() is page.html_preview
    assert 'Policy Inventory' in page.html_preview.toPlainText()
    assert not page.html_preview.openLinks() and not page.html_preview.openExternalLinks()
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    assert page.report is None and not page.export_button.isEnabled()
    assert not page.text_preview.toPlainText() and not page.html_preview.toPlainText()


def test_report_worker_locks_snapshot_and_ignores_replaced_context(workbench, monkeypatch):
    from PySide6.QtGui import QCloseEvent

    from oci_policy_analysis.application.services.reports_service import ReportsService

    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    page = window.tools_page.reports
    release = threading.Event()
    original = ReportsService.get_report

    def blocked(service, report_id):
        assert release.wait(10)
        return original(service, report_id)

    monkeypatch.setattr(ReportsService, 'get_report', blocked)
    page.run_button.click()
    try:
        assert 'report' in window.controller.load_block_reason
        assert not window.settings_page.sample_button.isEnabled()
        assert not window.simulation_page.isEnabled()
        event = QCloseEvent()
        window.closeEvent(event)
        assert not event.isAccepted()
        window.settings_page.load_sample()
        assert window.controller.worker is None
        page.set_context(None)
    finally:
        release.set()
        _wait_for_reports(application, window)
    assert page.report is None and not page.export_button.isEnabled()
    assert not window.controller.load_block_reason
    assert window.settings_page.sample_button.isEnabled()


def test_reports_show_full_profile_requirement_and_recover_from_errors(workbench, monkeypatch):
    from oci_policy_analysis.application.services.reports_service import ReportsService

    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    page = window.tools_page.reports
    page.report_choice.setCurrentIndex(page.report_choice.findData('permissions'))
    assert not page.run_button.isEnabled()
    assert 'Full intelligence' in page.description.text()
    context = window.controller.context
    context.intelligence.build_permissions_report(context.corpus)
    page.set_context(context)
    assert page.run_button.isEnabled()
    page.run_button.click()
    _wait_for_reports(application, window)
    assert page.report['report_id'] == 'permissions'
    for report_id in ['supersession', 'full-overlaps']:
        page.report_choice.setCurrentIndex(page.report_choice.findData(report_id))
        assert page.report is None
        page.run_button.click()
        _wait_for_reports(application, window)
        assert page.report['report_id'] == report_id
    monkeypatch.setattr(
        ReportsService, 'get_report', lambda *a: (_ for _ in ()).throw(RuntimeError('report unavailable'))
    )
    page.run_button.click()
    _wait_for_reports(application, window)
    assert 'report unavailable' in page.status.text()
    assert page.report is None and not page.export_button.isEnabled()
    assert page.run_button.isEnabled() and not window.controller.load_block_reason


def test_report_html_cannot_fetch_local_or_remote_resources(workbench):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QTextDocument

    _, window = workbench
    preview = window.tools_page.reports.html_preview
    for url in ['file:///etc/passwd', 'https://example.invalid/private.png']:
        assert preview.loadResource(QTextDocument.ResourceType.ImageResource, QUrl(url)).isEmpty()


def _wait_for_recommendations(application, window):
    deadline = time.monotonic() + 30
    while window.recommendations_page.worker is not None and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.01)
    assert window.recommendations_page.worker is None, 'Recommendation analysis did not finish'


def test_recommendations_run_builds_reports_and_rebinds_consumers(workbench, monkeypatch):
    from oci_policy_analysis.application.services.recommendations_service import RecommendationsService
    from oci_policy_analysis.application.services.reports_service import ReportsService

    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    page = window.recommendations_page
    context = window.controller.context
    records = window.prospective_page.service.records
    prospect = records.create(
        'ROOT/Applications',
        'Preserve local what-if',
        'allow group AppDevelopers to read buckets in compartment Applications',
    )
    records.validate_and_update_text(prospect.id, prospect.statement_text)
    records.persist_and_push_to_engine()
    prospective_ids = {row['internal_id'] for row in context.simulation.get_prospective_statements()}
    previous_simulation = context.simulation
    assert not context.intelligence.permissions_report
    assert 'Query foundations' in page.status.text()
    original = RecommendationsService.refresh_analysis
    threads = []

    def run(service, **kwargs):
        threads.append(QThread.currentThread() is application.thread())
        return original(service, **kwargs)

    monkeypatch.setattr(RecommendationsService, 'refresh_analysis', run)
    window.controller.settings['enabled_intelligence_checks'] = ['risk', 'supersession', 'recommendations']
    page.where_reduction.setCurrentIndex(page.where_reduction.findData(25))
    page.run_button.click()
    _wait_for_recommendations(application, window)
    assert threads == [False]
    assert context.simulation is not previous_simulation
    assert prospective_ids == {row['internal_id'] for row in context.simulation.get_prospective_statements()}
    assert context.simulation.get_prospective_statements()[0]['statement_text'] == prospect.statement_text
    prospect.description = 'Updated after engine replacement'
    records.persist_and_push_to_engine()
    assert context.simulation.get_prospective_statements()[0]['description'] == prospect.description
    assert context.intelligence.permissions_report
    assert page.tables['summary'].model.rowCount() > 0
    assert page.tables['risk_statement'].model.rowCount() > 0
    assert context.settings['risk_where_clause_reduction_pct'] == 25
    assert context.settings['enabled_intelligence_checks'] == ['risk', 'supersession', 'recommendations']
    assert window.simulation_page.controller.context is context
    assert window.tools_page.reports.context is context
    reports = window.tools_page.reports
    reports.report_choice.setCurrentIndex(reports.report_choice.findData('permissions'))
    assert reports.run_button.isEnabled()
    reports.run_report()
    _wait_for_reports(application, window)
    assert reports.report['report_id'] == 'permissions'
    assert ReportsService(context).get_report('supersession')['report_id'] == 'supersession'
    assert page.run_button.isEnabled()
    assert not window.controller.load_block_reason


def test_recommendations_filters_numeric_sort_and_formatted_supersession(workbench):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel

    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    context = window.controller.context
    candidate = context.policy_repo.regular_statements[0]
    candidate['statement_text'] = '<literal & source> ' + 'long policy text ' * 80
    candidate['effective_path'] = 'ROOT/Applications/Child'
    context.intelligence.overlay['supersessions'] = [
        {
            'statement_internal_id': candidate['internal_id'],
            'classification': 'Single Statement',
            'candidate_permissions': ['READ', 'WRITE'],
            'notes': 'Full unconditional coverage.',
            'evidence': [
                {
                    'policy_name': '<Ancestor>',
                    'statement_text': 'allow group Admin to manage all-resources in tenancy',
                    'effective_path': 'ROOT',
                    'relationship': 'Ancestor',
                    'covered_permissions': ['READ', 'WRITE'],
                    'conditional': False,
                },
                {
                    'policy_name': 'Qualified',
                    'statement_text': "allow any-user to read buckets in tenancy where request.user.id = 'alice'",
                    'effective_path': 'ROOT',
                    'relationship': 'Ancestor',
                    'covered_permissions': ['READ'],
                    'conditional': True,
                },
            ],
        }
    ]
    context.intelligence.overlay['recommendations'] = [
        {'Priority': 'High', 'Category': 'Risk', 'Recommendation': 'Review broad access'},
        {'Priority': 'Low', 'Category': 'Cleanup', 'Recommendation': 'Review objects'},
    ]
    page = window.recommendations_page
    page.set_context(context)
    page.severity.setCurrentIndex(page.severity.findData('High'))
    assert page.tables['summary'].model.rowCount() == 1
    page.searches['summary'].setText('absent')
    assert page.tables['summary'].proxy.rowCount() == 0
    page.searches['summary'].clear()
    page.category.setCurrentIndex(page.category.findData('Cleanup'))
    assert page.tables['summary'].model.rowCount() == 0
    page.compartment.setCurrentIndex(page.compartment.findData('ROOT/Applications'))
    table = page.tables['supersession']
    assert table.model.rowCount() == 1  # descendant included
    menu = table.context_menu(table.model.records[0])
    menu.actions()[0].trigger()
    menu.deleteLater()
    dialog = page.dialog
    assert dialog is not None
    assert dialog.details['candidate']['statement_text'] == candidate['statement_text']
    assert any(widget.text() == candidate['statement_text'] for widget in dialog.findChildren(QLabel))
    assert all(widget.textFormat() == Qt.TextFormat.PlainText for widget in dialog.findChildren(QLabel))
    assert dialog.coverage.model.records[1]['Conditional evidence (review only)'] == 'None'
    raw = dialog.raw.toPlainText()
    dialog._coverage_details(dialog.coverage.model.records[0])
    assert dialog.raw.toPlainText() == raw  # Copy all remains complete
    risk = page.tables['risk_statement']
    risk.model.replace([{'Relative Risk': 9}, {'Relative Risk': 100}, {'Relative Risk': 20}])
    risk.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    assert [risk.record_at(risk.proxy.index(i, 0))['Relative Risk'] for i in range(3)] == [100, 20, 9]
    page.set_context(None)
    assert page.dialog is None and not page.run_button.isEnabled()
    assert page.tables['supersession'].model.rowCount() == 0


def test_recommendations_worker_gates_competing_tasks_and_recovers_failure(workbench, monkeypatch):
    from oci_policy_analysis.application.services.recommendations_service import RecommendationsService

    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    page = window.recommendations_page
    context = window.controller.context
    entered, release = threading.Event(), threading.Event()

    def fail(service, **kwargs):
        entered.set()
        release.wait(10)
        raise RuntimeError('deliberate incomplete enrichment')

    monkeypatch.setattr(RecommendationsService, 'refresh_analysis', fail)
    page.run_analysis()
    assert entered.wait(5)
    try:
        page.run_analysis()  # duplicate submission ignored
        assert window.controller.load_block_reason
        assert not window.tools_page.reports.run_button.isEnabled()
        assert not window.mcp_page.start_button.isEnabled()
        window.settings_page.advanced_mode.setChecked(True)
        assert not window.browser_page.isEnabled()
        window.close()
        assert window.recommendations_page.worker is not None
    finally:
        release.set()
    _wait_for_recommendations(application, window)
    assert 'deliberate incomplete enrichment' in page.status.text()
    assert page.run_button.isEnabled()
    assert window.tools_page.reports.context is context
    assert not window.controller.load_block_reason
    window._mcp_locked(True)
    assert not page.run_button.isEnabled()
    window._mcp_locked(False)
    assert page.run_button.isEnabled()


def test_recommendations_reject_obsolete_worker_results(workbench, monkeypatch):
    from oci_policy_analysis.application.context import AppContext
    from oci_policy_analysis.application.services.recommendations_service import RecommendationsService

    application, window = workbench
    window.settings_page.load_sample()
    _wait_for_load(application, window)
    page = window.recommendations_page
    release = threading.Event()

    def obsolete(service, **kwargs):
        release.wait(10)
        return {'summary': [{'Recommendation': 'Obsolete result'}]}

    monkeypatch.setattr(RecommendationsService, 'refresh_analysis', obsolete)
    page.run_analysis()
    new_context = AppContext.from_settings({})
    window.controller.context = new_context
    page.set_context(new_context)
    release.set()
    _wait_for_recommendations(application, window)
    assert not page.payload['summary']
    assert page.context is new_context


def _wait_for_historical(application, window):
    deadline = time.monotonic() + 20
    while window.historical_page.worker is not None and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.01)
    assert window.historical_page.worker is None, 'Historical comparison did not finish'


def _historical_sources(page, left, right):
    for combo, name in zip(page.sources, (left, right), strict=True):
        combo.addItem(name, {'kind': 'cache', 'value': name})
        combo.setCurrentIndex(combo.count() - 1)


def test_historical_advanced_navigation_comparison_and_json_inspection(workbench, monkeypatch, tmp_path):
    from copy import deepcopy

    from PySide6.QtCore import Qt

    application, window = workbench
    page = window.historical_page
    assert window.navigation.item(window.page_index('historical')).isHidden()
    assert window.page_index('historical') + 1 == window.page_index('tools')
    window.experience.set_advanced(True)
    assert window.navigation.item(window.page_index('historical')).flags() & Qt.ItemFlag.ItemIsEnabled
    window.navigation.setCurrentRow(window.page_index('historical'))
    assert window.pages.currentWidget() is page
    assert window.controller.context is None
    left = {
        'tenancy_ocid': 'T',
        'policies': [{'policy_ocid': 'p', 'policy_name': '<Literal>', 'tags': {'cost.center': None}}],
        'policy_statements': [],
        'groups': [{'group_ocid': 'g', 'group_name': 'Before'}],
    }
    right = deepcopy(left)
    right['policies'][0]['tags'] = {'cost.center': 'new'}
    right['groups'][0]['group_name'] = 'After'
    threads = []

    def read(*, cached_tenancy):
        threads.append(QThread.currentThread() is application.thread())
        return deepcopy(left if cached_tenancy == 'baseline' else right)

    monkeypatch.setattr(page.cache, 'load_cache_into_local_json', read)
    _historical_sources(page, 'baseline', 'target')
    page.compare_button.click()
    _wait_for_historical(application, window)
    assert threads == [False, False]
    assert page.result and page.tables['policy'].model.rowCount() == 1
    assert page.tables['iam'].model.rowCount() == 1
    assert window.controller.context is None
    table = page.tables['policy']
    table.setCurrentIndex(table.proxy.index(0, 0))
    application.processEvents()
    assert page.selected_change['title'] == '<Literal>'
    assert page.changes.model().item(0).text() == 'tags'
    assert page.changes.model().item(0).child(0).text() == 'cost.center'
    assert page.field_values[0].toPlainText() == 'null'
    assert page.field_values[1].toPlainText() == '"new"'
    page.show_details()
    assert page.detail_window.isVisible()
    page.copy_change()
    assert json.loads(application.clipboard().text())['old_value'] == page.selected_change['old_value']
    export = tmp_path / 'comparison.json'
    monkeypatch.setattr(
        'oci_policy_analysis.presentation.qt.pages.historical.QFileDialog.getSaveFileName',
        lambda *args: (str(export), ''),
    )
    page.export_comparison()
    assert json.loads(export.read_text())['left_cache'] == 'baseline'
    page.searches['policy'].setText('no matches')
    assert table.proxy.rowCount() == 0 and page.selected_change is None
    page.swap_sources()
    assert page.result is None
    assert page.sources[0].currentData()['value'] == 'target'
    assert page.sources[1].currentData()['value'] == 'baseline'
    assert page.counts['policy'].text() == 'No current comparison.'
    assert page.sections['policy'].count() == 1
    assert not page.detail_window.isVisible()


def test_historical_json_file_inputs_skip_inherited_iam_and_do_not_rewrite(workbench, monkeypatch, tmp_path):
    application, window = workbench
    page = window.historical_page
    window.experience.set_advanced(True)
    left = {'tenancy_ocid': 'T', 'policies': [], 'groups': [{'group_ocid': 'g'}], 'users': []}
    right = {**left, 'snapshot_kind': 'policy_reload'}
    paths = [tmp_path / 'baseline.json', tmp_path / 'target.json']
    for path, source in zip(paths, (left, right), strict=True):
        path.write_text(json.dumps(source))
    before = [path.read_bytes() for path in paths]
    choices = iter(paths)
    monkeypatch.setattr(
        'oci_policy_analysis.presentation.qt.pages.historical.QFileDialog.getOpenFileName',
        lambda *args: (str(next(choices)), ''),
    )
    page.open_file(0)
    page.open_file(1)
    page.compare()
    _wait_for_historical(application, window)
    assert 'Groups' in page.result.skipped_sections
    page.sections['iam'].setCurrentIndex(page.sections['iam'].findData('Groups'))
    assert 'inherited' in page.counts['iam'].text()
    assert page.tables['iam'].model.rowCount() == 0
    assert [path.read_bytes() for path in paths] == before
    page.meaningful.setChecked(False)
    assert page.result is None and page.before.model().rowCount() == 0
    paths[1].write_text('{broken')
    page.compare()
    _wait_for_historical(application, window)
    assert 'Comparison failed' in page.status.text()
    assert page.compare_button.isEnabled() and not window.controller.load_block_reason


def test_historical_retains_worker_blocks_close_and_discards_stale_results(workbench, monkeypatch):
    application, window = workbench
    page = window.historical_page
    window.experience.set_advanced(True)
    entered, release = threading.Event(), threading.Event()

    def read(*, cached_tenancy):
        entered.set()
        release.wait(10)
        return {'tenancy_ocid': 'T', 'policies': []}

    monkeypatch.setattr(page.cache, 'load_cache_into_local_json', read)
    _historical_sources(page, 'baseline', 'target')
    page.compare()
    assert entered.wait(5)
    try:
        worker = page.worker
        page.compare()
        assert page.worker is worker
        assert window.controller.load_block_reason
        assert not window.settings_page.sample_button.isEnabled()
        assert not window.tools_page.reports.run_button.isEnabled()
        window.close()
        assert page.worker is not None
        page._invalidate()  # forced programmatic source change rejects old completion
    finally:
        release.set()
    _wait_for_historical(application, window)
    assert page.result is None
    assert not window.controller.load_block_reason
    assert window.settings_page.sample_button.isEnabled()


def test_lazy_json_model_preserves_types_paths_and_only_materializes_expanded_nodes(qt_application):
    from oci_policy_analysis.presentation.qt.json_view import JsonModel

    source = {'literal.key': [None, True, 1, '<text>'], 'many': list(range(10000))}
    model = JsonModel(source)
    root = model.index(0, 0)
    assert model.root.children[0].children == {}
    assert model.rowCount(root) == 2
    array = model.index(0, 0, root)
    assert model.parent(array) == root
    null = model.index(0, 1, array)
    assert model.data(null) == 'null'
    assert model.data(model.index(1, 1, array)) == 'true'
    assert model.data(model.index(2, 1, array)) == '1'
    assert model.data(model.index(3, 1, array)) == '"<text>"'
    assert model.parent(null) == array
    assert len(model.root.children[0].children) == 1  # second large array never visited


@pytest.mark.parametrize('successful_load', [True, False])
def test_live_qt_load_saves_snapshot_for_history_only_after_success(workbench, monkeypatch, successful_load):
    from copy import deepcopy

    from oci_policy_analysis.application.core.repo.policy_analysis_repository import PolicyAnalysisRepository

    application, window = workbench
    snapshot = sample_snapshot()

    def initialize(repo, **kwargs):
        if not successful_load:
            return False
        return caching.CacheManager().load_cache_from_json(loaded_json=deepcopy(snapshot), policy_analysis=repo)

    monkeypatch.setattr(PolicyAnalysisRepository, 'initialize_client', initialize)
    for method in ('load_compartments_only', 'load_complete_identity_domains', 'load_policies_only'):
        monkeypatch.setattr(PolicyAnalysisRepository, method, lambda *args, **kwargs: True)
    window.settings_page.load_button.click()
    _wait_for_load(application, window)
    names = window.settings_page.cache_service.list_caches()
    if not successful_load:
        assert not names
        assert window.controller.context is None
        return
    assert len(names) == 1
    saved = window.controller.context.cache.load_cache_into_local_json(cached_tenancy=names[0])
    assert saved['version'] == 2 and saved['schema_version'] == 3
    assert len(saved['policy_statements']) == len(snapshot['policy_statements'])
    assert window.settings_page.cache_list.currentData() == names[0]
    for combo in window.historical_page.sources:
        assert any(combo.itemData(i) == {'kind': 'cache', 'value': names[0]} for i in range(combo.count()))
