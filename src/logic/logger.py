import logging
from logging.handlers import RotatingFileHandler

_logger = None


def get_logger(use_console: bool = False) -> logging.Logger:
    """
    Global app logger, shared everywhere.

    Args:
        use_console (bool): If True, log to console only.
                            Default is False (log to app.log).
    """
    global _logger
    if _logger is None:
        _logger = logging.getLogger('oci-policy-analysis')
        _logger.setLevel(logging.INFO)

    # Always clear old handlers and re-add depending on flag
    if _logger.handlers:
        _logger.handlers.clear()

    if use_console:
        handler = logging.StreamHandler()
    else:
        handler = RotatingFileHandler('app.log', maxBytes=1_000_000, backupCount=3)

    handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    _logger.addHandler(handler)

    return _logger
