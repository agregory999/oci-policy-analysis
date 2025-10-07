import logging
from logging.handlers import RotatingFileHandler

_logger: logging.Logger | None = None


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
        _logger.propagate = False  # prevent duplicate logs via root logger

    # Remove all existing handlers to avoid duplicates
    if _logger.handlers:
        for h in _logger.handlers[:]:
            _logger.removeHandler(h)
            h.close()

    # Create the appropriate handler
    if use_console:
        handler = logging.StreamHandler()
    else:
        handler = RotatingFileHandler('app.log', maxBytes=1_000_000, backupCount=3)

    # Set consistent formatting
    handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    _logger.addHandler(handler)

    return _logger
