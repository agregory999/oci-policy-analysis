"""Compatibility shim for web module dependencies."""

import sys

from oci_policy_analysis.presentation.web import dependencies as _module

sys.modules[__name__] = _module
