import os
import sys
from pathlib import Path

# -- Project info -----------------------------------------------------
project = 'OCI Policy Analysis'
author = 'Andrew Gregory'
release = '0.1.0'

# -- General config ---------------------------------------------------
extensions = [
    'sphinx.ext.viewcode',
    'sphinx.ext.napoleon',
]

# Detect mode: CI (full autodoc) or local (lightweight)
if os.getenv('CI') in ('true', '1', 'True'):
    print('⚡ Sphinx: Running in FULL autodoc mode (CI)')
    extensions.extend(
        [
            'sphinx.ext.autodoc',
            'sphinx.ext.autosummary',
        ]
    )
else:
    print('⚡ Sphinx: Running in LIGHTWEIGHT mode (no autodoc)')

templates_path = ['_templates']
exclude_patterns = []

# -- Options for HTML output ------------------------------------------
html_theme = 'furo'
html_static_path = ['_static']

# -- Path setup -------------------------------------------------------
# Add src/ to sys.path so autodoc can find modules when enabled
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
