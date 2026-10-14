"""Catch dependency incompatibilities in the desktop's embedded MCP startup chain."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(importlib.util.find_spec('fastmcp') is None, reason='Embedded MCP extra is not installed')
def test_desktop_startup_imports_and_typed_mcp_metadata(tmp_path):
    root = Path(__file__).parents[2]
    env = {**os.environ, 'HOME': str(tmp_path)}
    completed = subprocess.run(
        [sys.executable, str(root / 'scripts/check_desktop_imports.py')],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert 'Desktop startup imports passed:' in completed.stdout
