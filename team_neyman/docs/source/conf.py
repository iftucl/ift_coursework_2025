# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import os
import sys

sys.path.insert(0, os.path.abspath("../../coursework_one"))

project = "ift_coursework_neyman"
copyright = "2026, Team Neyman"
author = "Ryan"
release = "en"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",  # Pulls docstrings from code
    "sphinx.ext.napoleon",  # Lets Sphinx read "Google Style" docstrings
    "sphinx.ext.viewcode",  # Adds "Source" links next to your functions
]

templates_path = ["_templates"]
exclude_patterns = []
autodoc_mock_imports = ["pandas", "sqlalchemy", "psycopg2", "minio", "yaml", "pyarrow"]


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
