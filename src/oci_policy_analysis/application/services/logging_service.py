"""Service facade for log level configuration."""

from __future__ import annotations

from dataclasses import dataclass

from oci_policy_analysis.common.logger import get_logger, set_component_level, set_log_level

LEGACY_COMPONENT_ALIASES: dict[str, tuple[str, ...]] = {
    # Core repo
    'data_repo': ('core.repo.policy_analysis_repository',),
    'reference_data_repo': ('core.repo.reference_data_repo',),
    'ai_repo': ('core.repo.ai',),
    # Core engines/parsers
    'policy_intelligence': ('core.engine.policy_intelligence_engine',),
    'policy_simulation_engine': ('core.engine.policy_simulation_engine',),
    'policy_parser': ('core.parser.policy_statement_normalizer',),
    'policy_subject_parser': ('core.parser.policy_subject_parser',),
    # Application services
    'analysis_service': ('application.services.analysis',),
    'cache_service': ('application.services.cache',),
    'condition_tester_service': ('application.services.condition_tester',),
    'consolidation_workbench_service': ('application.services.consolidation_workbench',),
    'historical_analysis_service': ('application.services.historical_analysis',),
    'intelligence_service': ('application.services.intelligence',),
    'load_service': ('application.services.load',),
    'logging_service': ('application.services.logging',),
    'policy_browser_service': ('application.services.policy_browser',),
    'principal_analysis_service': ('application.services.principal_analysis',),
    'recommendations_service': ('application.services.recommendations',),
    'reference_data_service': ('application.services.reference_data',),
    'settings_service': ('application.services.settings',),
    'simulation_service': ('application.services.simulation',),
    # Consumers
    'web_routes': ('web.api.routes_core',),
    'web_auth': ('web.auth',),
    'mcp_server': ('mcp.server',),
    'cli': ('cli.main',),
    'main': ('ui.main',),
}


def _expand_component_aliases(log_levels: dict[str, str]) -> dict[str, str]:
    """Expand user-provided component levels to include legacy/new alias pairs."""

    expanded = dict(log_levels)
    for component, level in list(log_levels.items()):
        aliases = LEGACY_COMPONENT_ALIASES.get(component, ())
        for alias in aliases:
            expanded.setdefault(alias, level)
        # Reverse-map: if user provides new taxonomy name only, apply to legacy too.
        for legacy, legacy_aliases in LEGACY_COMPONENT_ALIASES.items():
            if component in legacy_aliases:
                expanded.setdefault(legacy, level)
    return expanded


@dataclass
class LoggingService:
    """Apply and persist logging configuration."""

    settings: dict

    def __post_init__(self) -> None:
        """Initialize logger after dataclass construction.

        Returns:
            None
        """
        self.logger = get_logger(component='logging_service')

    def get_log_settings(self) -> dict:
        """Return current logging configuration values.

        Returns:
            dict: Effective logging settings.
        """
        base_levels = self.settings.get('log_levels', {})
        effective_levels = _expand_component_aliases(base_levels) if isinstance(base_levels, dict) else {}
        return {
            'global_log_level': self.settings.get('global_log_level', 'WARNING'),
            'log_levels': effective_levels,
            'always_log_timings': bool(self.settings.get('always_log_timings', False)),
            'always_log_api_calls': bool(self.settings.get('always_log_api_calls', False)),
        }

    def update_log_settings(self, updates: dict) -> dict:
        """Update logging configuration and apply runtime logger levels.

        Args:
            updates: Partial logging settings payload.

        Returns:
            dict: Updated effective logging settings.
        """
        self.logger.info('Updating logging settings with keys=%s', sorted(updates.keys()))
        if 'global_log_level' in updates:
            self.settings['global_log_level'] = updates['global_log_level']
            set_log_level(updates['global_log_level'])

        # Optional explicit reset of per-component overrides.
        if updates.get('clear_log_levels'):
            self.settings['log_levels'] = {}

        if 'log_levels' in updates and isinstance(updates['log_levels'], dict):
            if 'log_levels' not in self.settings:
                self.settings['log_levels'] = {}
            expanded_levels = _expand_component_aliases(updates['log_levels'])
            self.settings['log_levels'].update(expanded_levels)
            for comp, level in expanded_levels.items():
                set_component_level(comp, level)

        if 'always_log_timings' in updates:
            self.settings['always_log_timings'] = bool(updates['always_log_timings'])

        if 'always_log_api_calls' in updates:
            self.settings['always_log_api_calls'] = bool(updates['always_log_api_calls'])

        self.logger.info('Logging settings update complete')
        return self.get_log_settings()
