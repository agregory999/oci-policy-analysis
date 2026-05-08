"""Service facade for log level configuration."""

from __future__ import annotations

from dataclasses import dataclass

from oci_policy_analysis.common.logger import get_logger, set_component_level, set_log_level


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
        return {
            'global_log_level': self.settings.get('global_log_level', 'WARNING'),
            'log_levels': self.settings.get('log_levels', {}),
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
            self.settings['log_levels'].update(updates['log_levels'])
            for comp, level in updates['log_levels'].items():
                set_component_level(comp, level)

        if 'always_log_timings' in updates:
            self.settings['always_log_timings'] = bool(updates['always_log_timings'])

        if 'always_log_api_calls' in updates:
            self.settings['always_log_api_calls'] = bool(updates['always_log_api_calls'])

        self.logger.info('Logging settings update complete')
        return self.get_log_settings()
