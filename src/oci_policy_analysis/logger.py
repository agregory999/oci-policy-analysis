##########################################################################
# logger.py - unified global logger with component-level control
##########################################################################

import logging
import os
import sys
from logging.handlers import RotatingFileHandler


def _setup_logging() -> None:
    """Configure root logger once."""
    root = logging.getLogger()
    if root.handlers:  # Already setup? Skip.
        return

    root.setLevel(logging.INFO)  # Default level

    # Clear any existing handlers on root
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass

    # Add StreamHandler to root for shell console (all logs)
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] [%(name)s] %(message)s'))
    root.addHandler(stream)

    # Add rotating file handler (always, for EXE/shell)
    log_dir = os.path.expanduser('~/.oci-policy-analysis/logs')
    os.makedirs(log_dir, exist_ok=True)  # Create if needed (cross-platform safe)
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, 'app.log'),
        maxBytes=5 * 1024 * 1024,  # 5MB per file
        backupCount=3,  # Keep 3 rotated backups
    )
    file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] [%(name)s] %(message)s'))
    root.addHandler(file_handler)

    root.info('Root logger initialized (stdout + app.log).')


def get_logger(component: str | None = None) -> logging.Logger:
    """
    Return a component logger. No handlers added (propagate to root).
    """
    name = f'oci-policy-analysis.{component}' if component else 'oci-policy-analysis'
    lgr = logging.getLogger(name)
    lgr.propagate = True  # Ensure propagation to root
    return lgr


def set_log_level(level: str | int) -> None:
    """Set root level (affects everything)."""
    if isinstance(level, str):
        level_value = logging._nameToLevel.get(level.upper(), logging.INFO)
    else:
        level_value = int(level)

    # If we are in DEBUG, stay there (must have been passed in)
    if logging.getLogger().level == logging.DEBUG:
        logging.getLogger().debug('Root log level is DEBUG, not changing.')
        return
    root = logging.getLogger()
    root.setLevel(level_value)

    # Mirror to all oci-policy-analysis.* loggers (resets explicits)
    for name, obj in logging.root.manager.loggerDict.items():
        if isinstance(obj, logging.Logger) and name.startswith('oci-policy-analysis'):
            obj.setLevel(level_value)

    # logging.getLogger().setLevel(level_value)  # Root
    logging.getLogger().critical(f'Global (root) log level set to {logging.getLevelName(level_value)}')


def set_component_level(component: str, level: str | int) -> None:
    """Set level for a specific logger (app or third-party)."""
    if isinstance(level, str):
        level_value = logging._nameToLevel.get(level.upper(), logging.INFO)
    else:
        level_value = int(level)
    lgr = logging.getLogger(component) if '.' in component else get_logger(component)
    lgr.setLevel(level_value)
    logging.getLogger().info(f"Component log level for '{component}' set to {logging.getLevelName(level_value)}")


def dump_loggers():
    print('\n--- ACTIVE LOGGERS ---')
    root = logging.getLogger()
    handlers = [type(h).__name__ for h in root.handlers]
    print(f'root  level={logging.getLevelName(root.level)}  handlers={handlers}')
    for name, obj in logging.root.manager.loggerDict.items():
        if isinstance(obj, logging.Logger):
            handlers = [type(h).__name__ for h in obj.handlers]
            print(f'{name}  level={logging.getLevelName(obj.level)}  handlers={handlers}')
    print('-----------------------\n')


# This will get called whenever it is imported
_setup_logging()
