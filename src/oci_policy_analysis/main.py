"""Compatibility import for the Tkinter desktop application.

The maintained implementation lives in :mod:`oci_policy_analysis.presentation.tk.main`.
This module preserves the 7.0-era import path and command entry point.
"""

import importlib
import sys

if __name__ == '__main__':
    from .presentation.tk.main import main

    main()
else:
    # Keep module identity as well as exported names so existing monkeypatches
    # and imports continue to affect the Tk implementation's globals.
    _implementation = importlib.import_module('.presentation.tk.main', __package__)
    sys.modules[__name__] = _implementation
