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
    # If using MCP stdio mode, log to stderr to avoid mixing with MCP stdio
    if os.environ.get('MCP_STDIO_MODE', '0') == '1':
        stream = logging.StreamHandler(sys.stderr)  # Use stderr for logs
    else:
        stream = logging.StreamHandler(sys.stdout)  # Use stdout for logs
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

    Args:
        component: Component name (e.g., 'cli', 'data_repo'). If None, uses base name.

    Returns:
        Logger instance.
    """
    name = f'oci-policy-analysis.{component}' if component else 'oci-policy-analysis'
    lgr = logging.getLogger(name)
    lgr.propagate = True  # Ensure propagation to root
    return lgr


def set_log_level(level: str | int) -> None:
    """
    Set root level (affects everything). Log level int can be passed too. Options are:
        - CRITICAL  50
        - ERROR     40
        - WARNING   30
        - INFO      20
        - DEBUG     10

    Args:
        level: Level name (e.g., 'DEBUG') or int.
    """
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
    if isinstance(level, str):
        level_value = logging._nameToLevel.get(level.upper(), logging.INFO)
    else:
        level_value = int(level)
    lgr = logging.getLogger(component) if '.' in component else get_logger(component)
    lgr.setLevel(level_value)
    logging.getLogger().info(f"Component log level for '{component}' set to {logging.getLevelName(level_value)}")


# This will get called whenever it is imported
_setup_logging()
