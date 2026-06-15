"""Compatibility shim for web module auth."""

import sys

from oci_policy_analysis.presentation.web import auth as _module

sys.modules[__name__] = _module
