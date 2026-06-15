"""Compatibility shim for web core routes."""

import sys

from oci_policy_analysis.presentation.web.api import routes_core as _module

sys.modules[__name__] = _module
