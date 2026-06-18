from oci_policy_analysis.application.services.logging_service import LoggingService


def test_logging_service_canonicalizes_legacy_component_names():
    settings = {
        'log_levels': {
            'data_repo': 'DEBUG',
            'ai_repo': 'INFO',
            'policy_parser': 'WARNING',
            'web.api.routes_core': 'ERROR',
            'web.auth': 'CRITICAL',
            'mcp.server': 'INFO',
        }
    }

    service = LoggingService(settings)
    log_settings = service.get_log_settings()
    log_levels = log_settings['log_levels']

    assert log_levels['core.repo.policy_analysis_repository'] == 'DEBUG'
    assert log_levels['core.repo.ai_repo'] == 'INFO'
    assert log_levels['core.parser.policy_statement_normalizer'] == 'WARNING'
    assert log_levels['core.parser.policy_subject_parser'] == 'WARNING'
    assert log_levels['web_routes'] == 'ERROR'
    assert log_levels['web_auth'] == 'CRITICAL'
    assert log_levels['mcp_server'] == 'INFO'
    assert 'data_repo' not in log_levels
    assert 'ai_repo' not in log_levels
    assert 'policy_parser' not in log_levels
    assert 'web.api.routes_core' not in log_levels
    assert 'mcp.server' not in log_levels


def test_logging_service_update_writes_canonical_component_names():
    settings = {'log_levels': {'data_repo': 'INFO'}}
    service = LoggingService(settings)

    updated = service.update_log_settings({'log_levels': {'policy_parser': 'DEBUG'}})

    assert updated['log_levels']['core.repo.policy_analysis_repository'] == 'INFO'
    assert updated['log_levels']['core.parser.policy_statement_normalizer'] == 'DEBUG'
    assert updated['log_levels']['core.parser.policy_subject_parser'] == 'DEBUG'
    assert 'data_repo' not in service.settings['log_levels']
    assert 'policy_parser' not in service.settings['log_levels']
