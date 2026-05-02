from __future__ import annotations

import sys
from pathlib import Path

CW2_ROOT = Path(__file__).resolve().parents[1]
TEAM_ROOT = CW2_ROOT.parent
REPO_ROOT = TEAM_ROOT.parent

for path in (REPO_ROOT, TEAM_ROOT, CW2_ROOT):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

project = "Team Pearson CW2 Portfolio Research Platform"
author = "Team Pearson"
release = "2026.05"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "alabaster"
html_static_path = []

autodoc_member_order = "bysource"
autodoc_typehints = "description"
nitpicky = False
