import os
import sys

SOURCE_DIR = os.path.dirname(__file__)
CW1_ROOT = os.path.abspath(os.path.join(SOURCE_DIR, "..", "..", ".."))
REPO_ROOT = os.path.abspath(os.path.join(SOURCE_DIR, "..", "..", "..", "..", ".."))

sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, CW1_ROOT)
sys.path.insert(0, os.path.join(CW1_ROOT, "modules"))

project = "IFT Coursework 2025_team_Pearson"
copyright = "2026, Team Pearson"
author = "Team Pearson"
release = "0.1"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "myst_parser",
]

autodoc_default_options = {
    "member-order": "bysource",
}

autodoc_mock_imports = [
    "psycopg2",
    "pandas",
    "yfinance",
    "matplotlib",
    "matplotlib.pyplot",
    "matplotlib.dates",
    "matplotlib.ticker",
    "minio",
    "pymongo",
    "redis",
    "finnhub",
    "numpy",
    "pysentiment2",
    "langid",
    "sqlalchemy",
    "sqlalchemy.dialects",
    "sqlalchemy.dialects.postgresql",
    "requests",
    "yaml",
    "pydantic",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "alabaster"
html_static_path = ["_static"]
myst_heading_anchors = 3
