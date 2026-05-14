"""Version resolution helpers for OCI Policy Analysis."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from importlib.resources import files


def get_app_version(default: str = 'dev') -> str:
    """Return the application version.

    Build jobs generate ``version.txt`` before packaging executables and
    wheels. If that resource is absent in a local checkout, fall back to
    installed package metadata and then to the provided default.

    Args:
        default: Version string to return when no build or package metadata is
            available.

    Returns:
        The resolved application version.
    """

    try:
        raw_version = files('oci_policy_analysis').joinpath('version.txt').read_text()
        version = raw_version.lstrip('\ufeff').strip()
        if version:
            return version
    except Exception:
        pass

    try:
        return package_version('oci-policy-analysis')
    except PackageNotFoundError:
        return default
