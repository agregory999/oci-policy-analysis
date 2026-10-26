"""Optional PySide6 workbench over the installed application services.

Importing this adapter does not import PySide6 or construct an application.
The console and module launchers share the same dependency check.
"""

import sys


def main(argv: list[str] | None = None) -> int:
    """Launch the Qt workbench, explaining how to install its optional dependency.

    Args:
        argv: Command-line arguments; None uses the process arguments.

    Returns:
        int: Application exit status, or 2 when the qt extra is missing.

    Notes:
        Imports the UI only when called. Launching opens a local window; OCI
        collection and model requests require explicit actions in the UI.
    """
    try:
        from .main import main as run
    except ModuleNotFoundError as exc:
        if exc.name != 'PySide6' and not str(exc.name).startswith('PySide6.'):
            raise
        print('Qt requires PySide6. Install it with: python -m pip install "oci-policy-analysis[qt]"', file=sys.stderr)
        return 2
    return run(argv)
