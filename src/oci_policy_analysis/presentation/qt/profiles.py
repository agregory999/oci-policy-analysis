"""Discover profile names without loading credentials or authenticating."""

import configparser
from pathlib import Path


def profile_names(path: Path | None = None) -> list[str]:
    """Return OCI config profile names without reading signing keys or authenticating.

    Args:
        path: Optional config path; defaults to ~/.oci/config.

    Returns:
        list[str]: DEFAULT followed by the other named profile sections.
    """
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read(path or Path.home() / '.oci' / 'config')
    return ['DEFAULT', *(name for name in parser.sections() if name != 'DEFAULT')]
