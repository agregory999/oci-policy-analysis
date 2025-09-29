import logging
from logging.handlers import RotatingFileHandler

_logger = None


def get_logger():
    """Global app logger, shared everywhere."""
    global _logger
    if _logger is None:
        _logger = logging.getLogger('oci-policy-analysis')
        if not _logger.handlers:
            _logger.setLevel(logging.INFO)  # default; main will override from settings if present
            fh = RotatingFileHandler('app.log', maxBytes=1_000_000, backupCount=3)
            fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
            _logger.addHandler(fh)
    return _logger
