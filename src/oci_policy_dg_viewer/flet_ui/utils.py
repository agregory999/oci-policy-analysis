import configparser
import json
import logging
from datetime import datetime
from pathlib import Path


class LogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.logs: list[str] = []  # Full format logs
        self.short_logs: list[str] = []  # Short format logs

    def emit(self, record):
        full_format = self.format(record)
        short_format = f'{record.asctime.split()[1]} - {record.message}'
        self.logs.append(full_format)
        self.short_logs.append(short_format)

    def clear(self):
        """Clear stored logs."""
        self.logs.clear()
        self.short_logs.clear()


def setup_logging(level=logging.INFO):
    # Clear any existing handlers to avoid duplicates
    for handler in logging.getLogger().handlers[:]:
        logging.getLogger().removeHandler(handler)

    # Configure logger with full format for shell
    full_format = '%(asctime)s - %(threadName)s - %(module)s - %(levelname)s - %(message)s'
    logging.basicConfig(
        level=level,
        format=full_format,
        handlers=[logging.StreamHandler()],  # Always output to shell
    )
    logger = logging.getLogger()

    # Add custom handler for Console Log panel
    handler = LogHandler()
    handler.setFormatter(logging.Formatter(full_format))
    logger.addHandler(handler)
    return logger, handler


def set_logging_level(level_str: str):
    """Set global logging level."""
    level = logging.DEBUG if level_str == 'DEBUG' else logging.INFO
    logger = logging.getLogger()
    logger.setLevel(level)
    for handler in logger.handlers:
        handler.setLevel(level)


def get_app_dir():
    """Get or create ~/.iam-explorer/ directory."""
    app_dir = Path.home() / '.iam-explorer'
    app_dir.mkdir(exist_ok=True)
    return app_dir


def load_config():
    """Load configuration from ~/.iam-explorer/config.ini."""
    config = configparser.ConfigParser()
    config_file = get_app_dir() / 'config.ini'
    defaults = {
        'General': {'log_level': 'INFO', 'load_mode': 'profile'},
        'OCI': {'tenancy_ocid': '', 'config_profile': 'DEFAULT', 'cache_name': ''},
    }
    if config_file.exists():
        config.read(config_file)
    else:
        config.read_dict(defaults)
        save_config(config)
    return config


def save_config(config: configparser.ConfigParser):
    """Save configuration to ~/.iam-explorer/config.ini."""
    config_file = get_app_dir() / 'config.ini'
    with open(config_file, 'w') as f:
        config.write(f)


def list_oci_profiles():
    """List OCI config profiles from ~/.oci/config."""
    config_file = Path.home() / '.oci' / 'config'
    if not config_file.exists():
        return ['DEFAULT']
    config = configparser.ConfigParser()
    config.read(config_file)
    return config.sections()


def list_caches():
    """List available cache files in ~/.iam-explorer/ as 'tenancy - date'."""
    app_dir = get_app_dir()
    caches = []
    for file in app_dir.glob('cache-*.json'):
        parts = file.stem.split('-')
        if len(parts) >= 3:
            tenancy = parts[1]
            date = '-'.join(parts[2:])
            caches.append(f'{tenancy} - {date}')
    return caches


def load_cache(cache_name: str):
    """Load cached IAM data from ~/.iam-explorer/{cache_name}.json."""
    cache_file = get_app_dir() / f'{cache_name}.json'
    if cache_file.exists():
        try:
            with open(cache_file) as f:
                data = json.load(f)
                # Basic validation: check timestamp (e.g., within 24 hours)
                cache_time = datetime.fromisoformat(data.get('timestamp', '2000-01-01T00:00:00'))
                if (datetime.now() - cache_time).total_seconds() < 24 * 3600:
                    return data.get('data', {})
        except Exception as e:
            logger.error(f'Error loading cache {cache_name}: {e}')
    return None


def save_cache(data: dict, cache_name: str):
    """Save IAM data to ~/.iam-explorer/{cache_name}.json."""
    cache_file = get_app_dir() / f'{cache_name}.json'
    try:
        with open(cache_file, 'w') as f:
            json.dump({'timestamp': datetime.now().isoformat(), 'data': data}, f)
    except Exception as e:
        logger.error(f'Error saving cache {cache_name}: {e}')


logger, log_handler = setup_logging()
