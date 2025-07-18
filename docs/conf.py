"""Sphinx configuration for automatic documentation generation."""

import os
import sys

# Add source to path
sys.path.insert(0, os.path.abspath('../src'))

# Project info
project = 'OCI Policy Analysis'
copyright = '2025, Andrew Gregory'
author = 'Andrew Gregory'

# Get version dynamically
try:
    from importlib.metadata import version

    release = version('oci-policy-dg-viewer')
except ImportError:
    release = 'unknown'

# Extensions
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'autoapi.extension',
    'sphinx.ext.viewcode',
]

# AutoAPI settings - creates everything automatically
autoapi_type = 'python'
autoapi_dirs = ['../src']
autoapi_root = 'api'
autoapi_keep_files = False
autoapi_add_toctree_entry = False
autoapi_generate_api_docs = True

# HTML theme
html_theme = 'sphinx_rtd_theme'

# Napoleon settings
napoleon_google_docstring = True
napoleon_use_param = True
napoleon_use_rtype = True

# Set the master document (AutoAPI will create this)
master_doc = 'api/index'
