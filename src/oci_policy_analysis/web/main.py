"""Compatibility shim for web module main."""

import sys

from oci_policy_analysis.presentation.web import main as _module

sys.modules[__name__] = _module
