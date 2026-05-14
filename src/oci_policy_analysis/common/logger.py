##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# logger.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

import logging
import os
import sys
from logging.handlers import RotatingFileHandler


def _level_value(level: str | int | None, default: int = logging.INFO) -> int:
    """Return a logging level value from a string or integer input."""

    if level is None:
        return default
    if isinstance(level, int):
        return level
    value = str(level).strip()
    if not value:
        return default
    if value.isdigit():
        return int(value)
    return logging._nameToLevel.get(value.upper(), default)


def _resolve_logger_name(component: str) -> str:
    """Resolve configured component keys to concrete logger names.

    Supports both legacy short names (e.g. ``settings_tab``) and the newer
    taxonomy namespaces (e.g. ``core.engine.policy_intelligence_engine``)
    while still allowing explicit third-party logger names such as
    ``uvicorn.access``.
    """

    name = (component or '').strip()
    if not name:
        return 'oci-policy-analysis'

    if name.startswith('oci-policy-analysis.'):
        return name

    # Known third-party/runtime logger roots that should remain unprefixed.
    third_party_roots = {'uvicorn', 'fastapi', 'asyncio', 'urllib3', 'httpx', 'sqlalchemy'}
    if name in third_party_roots:
        return name
    if '.' in name and name.split('.', 1)[0] in third_party_roots:
        return name

    return f'oci-policy-analysis.{name}'


class ForceFlushStreamHandler(logging.StreamHandler):
    """Stream handler that flushes after every log record.

    This keeps console and MCP stderr logs visible promptly, including when
    records are emitted from worker threads.
    """

    def emit(self, record):
        super().emit(record)
        if self.stream:
            try:
                self.stream.flush()
            except Exception:
                pass


def _setup_logging() -> None:
    """
    Configure root logger and handlers once, early in process lifetime.

    - Always attaches a ForceFlushStreamHandler for shell/file logging (DEBUG shown here when enabled).
    - Handlers relevant to the in-app ConsoleTab (UI) should always filter at INFO or higher (see ConsoleTab implementation), never DEBUG.
    - No handler here will enforce INFO or higher: responsibility for filtering DEBUG from UI is solely in ConsoleTab.

    The rest of the application (including the UI) should only alter log levels via set_log_level/set_component_level, never by re-attaching handlers.
    """
    root = logging.getLogger()
    if root.handlers:  # Already setup? Skip.
        return

    root.setLevel(_level_value(os.environ.get('OCI_POLICY_ANALYSIS_LOG_LEVEL')))  # Default level

    # Clear any existing handlers on root
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass

    # Add StreamHandler to root for shell console (all logs)
    # If using MCP stdio mode, log to stderr to avoid mixing with MCP stdio
    if os.environ.get('MCP_STDIO_MODE', '0') == '1':
        stream = ForceFlushStreamHandler(sys.stderr)
    else:
        stream = ForceFlushStreamHandler(sys.stdout)
    stream.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] [%(name)s] %(message)s'))
    root.addHandler(stream)

    # Add rotating file handler (always, for EXE/shell); DEBUG records also routed here if enabled
    log_dir = os.path.expanduser('~/.oci-policy-analysis/logs')
    os.makedirs(log_dir, exist_ok=True)  # Create if needed (cross-platform safe)
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, 'app.log'),
        maxBytes=5 * 1024 * 1024,  # 5MB per file
        backupCount=3,  # Keep 3 rotated backups
    )
    file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] [%(name)s] %(message)s'))
    root.addHandler(file_handler)

    stream_name = 'stderr' if os.environ.get('MCP_STDIO_MODE', '0') == '1' else 'stdout'
    root.info('Root logger initialized (%s + app.log).', stream_name)


def get_logger(component: str | None = None) -> logging.Logger:
    """
    Return a component logger. No handlers added (propagate to root).

    Args:
        component: Component name (e.g., 'cli', 'data_repo'). If None, uses base name.

    Returns:
        Logger instance.
    """
    name = f'oci-policy-analysis.{component}' if component else 'oci-policy-analysis'
    lgr = logging.getLogger(name)
    lgr.propagate = True  # Ensure propagation to root
    return lgr


def set_log_level(level: str | int, announce: bool = True) -> None:
    """
    Set root logger level (affects all non-overridden loggers).

    - Use for global (root) logging threshold, e.g., on app startup or when user changes global log level.
    - When --verbose is active, will force DEBUG everywhere (but UI always filters DEBUG).
    - Do not use to configure UI/ConsoleTab handler; that always filters at INFO+.

    Options:
        - CRITICAL  50
        - ERROR     40
        - WARNING   30
        - INFO      20
        - DEBUG     10

    Args:
        level: Level name (e.g., 'DEBUG') or int.
        announce: Whether to log the resulting level change.
    """
    level_value = _level_value(level)

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

    # Also mirror to uvicorn loggers when running web mode so access/error
    # output respects the same global threshold (e.g., WARNING hides
    # frequent INFO request lines like "GET /status 200 OK").
    for logger_name in ('uvicorn', 'uvicorn.error', 'uvicorn.access'):
        logging.getLogger(logger_name).setLevel(level_value)

    # logging.getLogger().setLevel(level_value)  # Root
    if announce:
        logging.getLogger().warning(f'Global (root) log level set to {logging.getLevelName(level_value)}')


def set_component_level(component: str, level: str | int) -> None:
    """
    Set level for a specific logger (app or third-party).
    Component can be full logger name (with dots) or just base name.
    Example: set_component_level('cli', 'DEBUG')

    Args:
        component: Component/logger name (e.g., 'cli', 'data_repo', 'requests')
        level: Level name (e.g., 'DEBUG') or int.
    """
    root = logging.getLogger()
    # If root is DEBUG, --verbose is active, override any request to set lower level.
    logger_name = _resolve_logger_name(component)

    if root.level == logging.DEBUG:
        level_value = logging.DEBUG
        lgr = logging.getLogger(logger_name)
        lgr.setLevel(level_value)
        logging.getLogger().info(f"Component log level for '{component}' forced to DEBUG due to root/verbose override")
        return
    if isinstance(level, str):
        level_value = logging._nameToLevel.get(level.upper(), logging.INFO)
    else:
        level_value = int(level)
    lgr = logging.getLogger(logger_name)
    lgr.setLevel(level_value)
    logging.getLogger().critical(f"Component log level for '{component}' set to {logging.getLevelName(level_value)}")


# This will get called whenever it is imported
_setup_logging()
