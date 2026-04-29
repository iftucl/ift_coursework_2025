import os
import sys

sys.path.insert(0, os.path.abspath("../../a_pipeline"))  # Points to a_pipeline root

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx_rtd_theme",
]

autodoc_mock_imports = [
    "minio",
    "psycopg",
    "sqlalchemy",
    "pandas",
    "numpy",
    "yfinance",
    "dots",
]

html_theme = "sphinx_rtd_theme"

# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "IFTE Big Data Coursework One"
copyright = "2026, Team Neyman"
author = "Team Neyman"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

templates_path = ["_templates"]
exclude_patterns = []


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_static_path = ["_static"]
