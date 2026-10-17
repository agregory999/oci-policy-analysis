"""Offline startup verification used by local Qt executable builds."""

import asyncio
import json
import tempfile
import time
from pathlib import Path


def main() -> int:
    """Check packaged Qt, resources, snapshot loading, and MCP typed metadata.

    Returns:
        int: Zero after successful offline checks. Failures raise an exception.

    Notes:
        Uses temporary settings/cache storage and never connects to OCI or starts
        an MCP listener. The external Codex executable is not part of the bundle.
    """
    from mcp.server.fastmcp.utilities.func_metadata import func_metadata
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    from oci_policy_analysis.application.context import AppContext
    from oci_policy_analysis.application.core.support import caching, config
    from oci_policy_analysis.application.services.load_service import LoadService
    from oci_policy_analysis.application.services.principal_analysis_service import PrincipalAnalysisService
    from oci_policy_analysis.presentation.qt.main import WorkbenchWindow
    from oci_policy_analysis.presentation.qt.sample_data import sample_snapshot

    def smoke_tool(value: str) -> str:
        return value

    metadata = func_metadata(smoke_tool)
    assert metadata.arg_model.model_validate({'value': 'smoke'}).value == 'smoke'
    application = QApplication.instance() or QApplication(['opa-qt-self-test'])
    old_cache, old_settings = caching.CACHE_DIR, config.SETTINGS_PATH
    try:
        with tempfile.TemporaryDirectory(prefix='opa-qt-frozen-smoke-') as directory:
            root = Path(directory)
            caching.CACHE_DIR = root / 'cache'
            config.SETTINGS_PATH = str(root / 'settings.json')
            context = AppContext.from_settings({})
            source = root / 'sample.json'
            source.write_text(json.dumps(sample_snapshot()), encoding='utf-8')
            result = LoadService(context).load_from_export_json(str(source), post_load_profile='minimal')
            assert result.success, result.message
            assert context.policy_repo.users and context.policy_repo.groups
            assert PrincipalAnalysisService(context).by_groups_users(users=context.policy_repo.users[:1]).statements

            from fastmcp import Client

            from oci_policy_analysis.mcp_server import create_snapshot_server

            async def verify_mcp():
                server = await create_snapshot_server(context)
                async with Client(server) as client:
                    tools = {tool.name for tool in await client.list_tools()}
                    assert {'snapshot_status', 'policy_search', 'identity_search'} <= tools
                    status = await client.call_tool('snapshot_status')
                    assert status.data['statements'] == len(context.policy_repo.regular_statements)
                    policies = await client.call_tool('policy_search', {'filters': {'exact_subject_types': ['group']}})
                    assert not policies.is_error and policies.data['total_count'] > 0

            asyncio.run(verify_mcp())
            window = WorkbenchWindow()
            window.controller.context = context
            window._publish(context, result, 'Packaged sample smoke test')
            from oci_policy_analysis.application.services.reports_service import ReportsService

            inventory_report = ReportsService(context).get_report('policy-inventory')
            assert inventory_report['counts']['statements'] == len(context.policy_repo.regular_statements)
            assert '<!doctype html>' in ReportsService(context).export_formats(inventory_report)['html']
            assert len(window.tools_page.reports.catalog) == 4
            reports = window.tools_page.reports
            reports.run_report()
            deadline = time.monotonic() + 30
            while reports.worker is not None and time.monotonic() < deadline:
                application.processEvents()
                time.sleep(0.01)
            assert reports.worker is None, 'Packaged report worker did not finish'
            assert reports.report and reports.report['report_id'] == 'policy-inventory'
            reports.format_choice.setCurrentIndex(reports.format_choice.findData('html'))
            assert 'Policy Inventory' in reports.html_preview.toPlainText()
            recommendations = window.recommendations_page
            window.controller.settings['enabled_intelligence_checks'] = ['risk', 'supersession', 'recommendations']
            recommendations.run_analysis()
            deadline = time.monotonic() + 60
            while recommendations.worker is not None and time.monotonic() < deadline:
                application.processEvents()
                time.sleep(0.01)
            assert recommendations.worker is None, 'Packaged recommendation worker did not finish'
            assert context.intelligence.permissions_report, recommendations.status.text()
            assert recommendations.tables['summary'].model.rowCount() > 0
            reports.report_choice.setCurrentIndex(reports.report_choice.findData('permissions'))
            assert reports.run_button.isEnabled(), 'Analysis did not enable permissions report'
            from oci_policy_analysis.presentation.qt.pages.recommendations import SupersessionDialog

            details = SupersessionDialog(
                {
                    'candidate': context.policy_repo.regular_statements[0],
                    'finding': {
                        'Classification': 'Formatting smoke check',
                        'Notes': 'No authorization conclusion.',
                        'Evidence': [],
                    },
                    'coverage': [],
                },
                window,
            )
            details.show()
            application.processEvents()
            assert details.tabs.count() == 3
            details.close()
            details.deleteLater()

            assert not window.windowIcon().isNull()
            assert window.users_groups_page.user_view.inventory.model.rowCount() == len(context.policy_repo.users)
            application.processEvents()
            window.close()
            application.processEvents()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            print('Qt executable smoke test passed: resources, sample, services, in-memory MCP queries')
    finally:
        caching.CACHE_DIR, config.SETTINGS_PATH = old_cache, old_settings
    return 0
