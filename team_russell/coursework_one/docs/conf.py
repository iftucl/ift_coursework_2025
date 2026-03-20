"""Sphinx configuration for Team Russell – Coursework One documentation."""

import os
import sys

# ---------------------------------------------------------------------------
# Path setup
# Add each pipeline root so autodoc can import modules without installation.
# ---------------------------------------------------------------------------
_here = os.path.dirname(os.path.abspath(__file__))
_cw1 = os.path.dirname(_here)  # coursework_one/

for _pipeline in ("a_pipeline", "b_pipeline", "c_pipeline"):
    sys.path.insert(0, os.path.join(_cw1, _pipeline))

# ---------------------------------------------------------------------------
# Project information
# ---------------------------------------------------------------------------
project = "Team Russell – IFT Coursework One"
copyright = "2025, Team Russell, University College London"
author = "Team Russell"
release = "0.5.0"

# ---------------------------------------------------------------------------
# General configuration
# ---------------------------------------------------------------------------
extensions = [
    "sphinx.ext.autodoc",  # pull docstrings from source
    "sphinx.ext.napoleon",  # Google / NumPy docstring styles
    "sphinx.ext.viewcode",  # link to highlighted source
    "sphinx.ext.intersphinx",  # cross-reference Python stdlib
    "sphinx.ext.todo",  # .. todo:: directives
]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pandas": ("https://pandas.pydata.org/docs/", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
}

# Napoleon settings – parse Google-style docstrings
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_use_param = True
napoleon_use_rtype = True

# autodoc defaults
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "private-members": False,
    "show-inheritance": True,
}
autodoc_typehints = "description"

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# ---------------------------------------------------------------------------
# HTML output
# ---------------------------------------------------------------------------
html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_theme_options = {
    "navigation_depth": 4,
    "titles_only": False,
}
