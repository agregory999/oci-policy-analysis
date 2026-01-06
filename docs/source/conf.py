import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join('..', '..', 'src')))

project = 'OCI Policy Analysis'
author = 'Andrew Gregory'
copyright = f'{datetime.now().year}, {author}'
release = '2.0.0'

extensions = [
    'myst_parser',
    'sphinx.ext.autodoc',
    'sphinx.ext.autosummary',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
    'sphinx.ext.todo',
    'sphinx.ext.intersphinx',
    'sphinxcontrib.mermaid',
]

source_suffix = {'.rst': 'restructuredtext', '.md': 'markdown'}
myst_enable_extensions = [
    'colon_fence',
    'deflist',
    'tasklist',
    'substitution',
    'attrs_block',
    'attrs_inline',
    'replacements',
]

autodoc_mock_imports = [
    'tkinter',
    'ttkbootstrap',
    '_tkinter',
]
myst_fence_as_directive = ['mermaid']

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
html_theme_options = {'navigation_depth': 3}  # only show H1 and H2 and H3 in sidebar
html_favicon = '_static/favicon.ico'
autosummary_generate = True
autodoc_member_order = 'bysource'
autodoc_default_options = {'members': True, 'undoc-members': False, 'show-inheritance': True}
napoleon_google_docstring = True
napoleon_numpy_docstring = False
intersphinx_mapping = {'python': ('https://docs.python.org/3', None)}
todo_include_todos = True
