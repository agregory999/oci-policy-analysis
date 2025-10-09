import logging
from logging.handlers import RotatingFileHandler

_base_logger: logging.Logger | None = None
_console_mode: bool | None = None


def _setup_base_logger(use_console: bool) -> logging.Logger:
    """Initialize the base logger with either console or file handler."""
    global _base_logger, _console_mode

    if _base_logger and _console_mode == use_console:
        return _base_logger

    _base_logger = logging.getLogger('oci-policy-analysis')
    _base_logger.setLevel(logging.INFO)
    _base_logger.propagate = False

    # Clear old handlers
    for h in _base_logger.handlers[:]:
        _base_logger.removeHandler(h)
        h.close()

    # Create handler
    if use_console:
        handler = logging.StreamHandler()
    else:
        handler = RotatingFileHandler('app.log', maxBytes=1_000_000, backupCount=3)

    formatter = logging.Formatter('%(asctime)s [%(levelname)s] [%(name)s] %(message)s')
    handler.setFormatter(formatter)
    _base_logger.addHandler(handler)

    _console_mode = use_console
    return _base_logger


def get_logger(component: str | None = None, use_console: bool | None = None) -> logging.Logger:
    """
    Get a named logger for a specific component.

    Args:
        component (str | None): e.g. 'data_repo', 'mcp', etc.
        use_console (bool | None): Force console mode on first call.
    """
    global _console_mode

    if _base_logger is None:
        _setup_base_logger(use_console if use_console is not None else False)
    elif use_console is not None and _console_mode != use_console:
        _setup_base_logger(use_console)

    name = f'oci-policy-analysis.{component}' if component else 'oci-policy-analysis'
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = True
    return logger


def set_log_level(level: str | int, component: str | None = None) -> None:
    """
    Dynamically set log level globally or for a specific component.

    Args:
        level (str | int): e.g. 'DEBUG', 'INFO', 'WARNING', etc. or logging.DEBUG
        component (str | None): If provided, applies only to that logger.
    """
    # Convert string level to numeric
    if isinstance(level, str):
        level = level.upper()
        if level not in logging._nameToLevel:
            raise ValueError(f'Invalid log level: {level}')
        level_value = logging._nameToLevel[level]
    else:
        level_value = int(level)

    # Target logger(s)
    if component:
        target = logging.getLogger(f'oci-policy-analysis.{component}')
        target.setLevel(level_value)
    else:
        base = logging.getLogger('oci-policy-analysis')
        base.setLevel(level_value)
        for name, logger in logging.root.manager.loggerDict.items():
            if name.startswith('oci-policy-analysis.'):
                logger.setLevel(level_value)
