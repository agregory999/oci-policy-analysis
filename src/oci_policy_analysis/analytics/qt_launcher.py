"""Optional Qt analytics command without eager GUI imports."""

import sys


def main(argv: list[str] | None = None) -> int:
    """Launch usage analytics, explaining how to install the Qt extra.

    Args:
        argv: Optional viewer command-line arguments.

    Returns:
        int: Qt exit status, or 2 when PySide6 is missing.
    """
    try:
        from .qt import main as run
    except ModuleNotFoundError as exc:
        if exc.name != 'PySide6' and not str(exc.name).startswith('PySide6.'):
            raise
        print('Analytics requires: python -m pip install "oci-policy-analysis[qt]"', file=sys.stderr)
        return 2
    return run(argv)
