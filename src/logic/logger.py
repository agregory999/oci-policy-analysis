##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0
# as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER: This is not an official Oracle application and
# is not supported by Oracle Support.
#
# logger.py - unified global logger (stdout only)
#
# @author: Andrew Gregory
##########################################################################

import logging
import sys

_base_logger: logging.Logger | None = None


def _setup_base_logger() -> logging.Logger:
    """Initialize the global base logger that outputs to stdout."""
    global _base_logger

    if _base_logger:
        return _base_logger

    _base_logger = logging.getLogger('oci-policy-analysis')
    _base_logger.setLevel(logging.INFO)
    _base_logger.propagate = False

    # Clear any old handlers (prevents duplicates if reloaded)
    for h in _base_logger.handlers[:]:
        _base_logger.removeHandler(h)
        h.close()

    # Single stdout handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] [%(name)s] %(message)s'))
    _base_logger.addHandler(handler)

    return _base_logger


def get_logger(component: str | None = None) -> logging.Logger:
    """
    Get a logger for a specific component.
    All component loggers share the same stdout handler.
    """
    if _base_logger is None:
        _setup_base_logger()

    name = f'oci-policy-analysis.{component}' if component else 'oci-policy-analysis'
    logger = logging.getLogger(name)
    logger.setLevel(_base_logger.level)
    logger.propagate = True
    return logger


def set_log_level(level: str | int) -> None:
    if isinstance(level, str):
        level = level.upper()
        if level not in logging._nameToLevel:
            raise ValueError(f'Invalid level: {level}')
        level_value = logging._nameToLevel[level]
    else:
        level_value = int(level)

    base = logging.getLogger('oci-policy-analysis')
    base.setLevel(level_value)

    # update all handlers on base and subloggers
    for name, lgr in logging.root.manager.loggerDict.items():
        if isinstance(lgr, logging.Logger) and name.startswith('oci-policy-analysis'):
            lgr.setLevel(level_value)
            for h in lgr.handlers:
                h.setLevel(level_value)

    base.info(f'Global log level set to {logging.getLevelName(level_value)}')


# Initialize immediately
logger = get_logger('logger')
logger.info('Logger initialized (stdout only).')
