"""Qt preferences using the shared application settings file."""

from oci_policy_analysis.application.services.settings_service import SettingsService
from oci_policy_analysis.presentation.qt.themes import COLOR_THEMES


def load_preferences() -> dict:
    """Read existing settings and supply safe Qt defaults without loading OCI.

    Returns:
        dict: Shared settings with Qt defaults; saved log levels apply unless --verbose overrides them.
    """
    settings = SettingsService.load().get()
    if settings.get('global_log_level') not in {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}:
        settings['global_log_level'] = 'INFO'
    settings.setdefault('log_levels', {})
    settings.setdefault('usage_tracking_enabled', True)
    if settings.get('qt_theme') not in {'Light', 'Dark'}:
        settings['qt_theme'] = 'Light'
    if settings.get('qt_color_theme') not in COLOR_THEMES:
        settings['qt_color_theme'] = 'Forest'
    if settings.get('font_size') not in {'Small', 'Medium', 'Large', 'Extra Large'}:
        settings['font_size'] = 'Medium'
    return settings


def save_preferences(settings: dict, keys: tuple[str, ...]) -> None:
    """Merge only requested preferences, preserving other interfaces' settings.

    Args:
        settings: Current settings containing requested values.
        keys: Explicit settings to persist.

    Raises:
        OSError: Shared settings writer did not retain the requested values.
    """
    service = SettingsService.load()
    updates = {key: settings[key] for key in keys if key in settings}
    service.update(updates)
    service.save()
    saved = SettingsService.load().get()
    if any(saved.get(key) != value for key, value in updates.items()):
        raise OSError('Could not save application preferences')
