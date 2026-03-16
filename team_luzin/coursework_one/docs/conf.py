# Configuration file for Sphinx documentation

import os
import sys

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

# Project information
project = 'Investment Strategy Data Pipeline'
copyright = '2026, Team Luzin'
author = 'Team Luzin'
release = '2.0.0'

# Sphinx extensions
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
    'sphinx.ext.intersphinx',
]

# Napoleon extension settings
napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_docstring = True
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = True
napoleon_use_admonition_for_notes = True
napoleon_use_admonition_for_references = False
napoleon_use_ivar = False
napoleon_use_param = True
napoleon_use_rtype = True
napoleon_preprocess_types = False
napoleon_type_aliases = None
napoleon_attr_annotations = True

# Autodoc settings
autodoc_default_options = {
    'members': True,
    'member-order': 'bysource',
    'special-members': '__init__',
    'undoc-members': False,
    'show-inheritance': True,
}

# HTML output settings
html_theme = 'sphinx_rtd_theme'
html_theme_options = {
    'logo_only': False,
    'display_version': True,
    'prev_next_buttons_location': 'bottom',
    'style_external_links': False,
    'vcs_pageview_mode': '',
    'style_path_in_sidebar': True,
    'analytics_id': '',
    'analytics_anonymize_ip': False,
    'sticky_navigation': True,
    'navigation_depth': 4,
    'includehidden': True,
    'titles_only': False
}

html_static_path = ['_static']
html_css_files = []
html_logo = None

# Source file suffix
source_suffix = '.rst'

# Master document
master_doc = 'index'

# Language
language = 'en'

# Pygments style
pygments_style = 'sphinx'

# Show warnings
keep_warnings = True


# Setup function
def setup(app):
    """Setup Sphinx application."""
    app.connect('autodoc-skip-member', skip_member)


def skip_member(app, what, name, obj, skip, options):
    """Skip private members in autodoc."""
    if name.startswith('_'):
        return True
    return skip
