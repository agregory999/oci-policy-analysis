"""Known dependency notices stay quiet without hiding other diagnostics."""

import subprocess
import sys
import warnings
from importlib.util import find_spec
from pathlib import Path

import pytest

from oci_policy_analysis.application.core.support.mcp_warnings import configure_mcp_dependency_warnings

AuthlibDeprecationWarning = pytest.importorskip('authlib.deprecate').AuthlibDeprecationWarning


def test_mcp_warning_filters_match_only_the_two_known_notices():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        configure_mcp_dependency_warnings()
        warnings.warn(
            'authlib.jose module is deprecated, please use joserfc instead.\n'
            'It will be compatible before version 2.0.0.',
            AuthlibDeprecationWarning,
            stacklevel=2,
        )
        warnings.warn(
            'The httpx module is deprecated; please use httpx2 instead.', AuthlibDeprecationWarning, stacklevel=2
        )
        warnings.warn('Another Authlib deprecation', AuthlibDeprecationWarning, stacklevel=2)
        warnings.warn(
            'The httpx module is deprecated; please use httpx2 instead. Changed notice.',
            AuthlibDeprecationWarning,
            stacklevel=2,
        )
        warnings.warn('The httpx module is deprecated; please use httpx2 instead.', RuntimeWarning, stacklevel=2)
    assert [str(item.message) for item in caught] == [
        'Another Authlib deprecation',
        'The httpx module is deprecated; please use httpx2 instead. Changed notice.',
        'The httpx module is deprecated; please use httpx2 instead.',
    ]


def test_fresh_fastmcp_import_does_not_emit_known_authlib_notices():
    if find_spec('fastmcp') is None:
        pytest.skip('MCP extra is not installed')
    helper = Path(__file__).parents[1] / 'oci_policy_analysis/application/core/support/mcp_warnings.py'
    result = subprocess.run(
        [
            sys.executable,
            '-c',
            'import runpy, sys, warnings; warnings.simplefilter("always"); '
            'runpy.run_path(sys.argv[1])["configure_mcp_dependency_warnings"](); '
            'from fastmcp import Client, FastMCP; print("MCP imports OK")',
            str(helper),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert 'MCP imports OK' in result.stdout
    assert 'AuthlibDeprecationWarning' not in result.stderr
