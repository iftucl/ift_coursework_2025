"""Sphinx configuration for CW1 Value + Sentiment Strategy documentation."""

import os
import sys

sys.path.insert(0, os.path.abspath(".."))

project = "Value + News Sentiment Strategy"
copyright = "2026, Team 09 — UCL IFT"
author = "Team 09"
release = "1.0.0"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
]

templates_path = ["_templates"]
exclude_patterns = ["_build"]

html_theme = "pydata_sphinx_theme"
html_static_path = ["_static"]

autodoc_member_order = "bysource"
napoleon_google_docstring = False
napoleon_numpy_docstring = False
napoleon_use_param = True
napoleon_use_rtype = True

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pandas": ("https://pandas.pydata.org/docs/", None),
}
