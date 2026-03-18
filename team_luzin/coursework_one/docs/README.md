# Sphinx Documentation

This directory contains comprehensive Sphinx documentation for the Investment Strategy Data Pipeline.

## Documentation Contents

### Getting Started
- **Installation**: Step-by-step installation and setup guide
- **Quick Start**: 5-minute quick start tutorial
- **Architecture**: Technical architecture overview and data flow

### User Guides
- **Usage**: Complete usage instructions and examples
- **Configuration**: Configuration guide and best practices

### API Reference
- **API Index**: Overview of all modules
- **Database Module**: PostgreSQL connectivity
- **Input Module**: Data loading and ingestion
- **Processing Module**: Factor calculations (risk, momentum, liquidity, scoring)
- **Signals Module**: Trading signal generation
- **Output Module**: Results export and reporting
- **Storage Module**: MinIO and data lake integration

### Support
- **Troubleshooting**: Common issues and solutions
- **FAQ**: Frequently asked questions

## Building Documentation

### Prerequisites
Sphinx and dependencies are included in Poetry:
```bash
poetry install
```

### Generate HTML Documentation
```bash
cd docs
poetry run sphinx-build -b html . _build/html
```

### View Documentation
```bash
# Open in browser
open _build/html/index.html  # macOS
xdg-open _build/html/index.html  # Linux

# Or serve locally
python3 -m http.server --directory _build/html 8000
# Then visit http://localhost:8000
```

## Documentation Structure

```
docs/
├── conf.py                      # Sphinx configuration
├── index.rst                    # Main documentation index
├── installation.rst             # Installation guide
├── quickstart.rst               # Quick start tutorial
├── architecture.rst             # Architecture overview
├── usage.rst                    # Usage instructions
├── configuration.rst            # Configuration guide
├── troubleshooting.rst          # Troubleshooting guide
├── faq.rst                      # Frequently asked questions
├── api/                         # API reference directory
│   ├── index.rst                # API reference index
│   ├── modules.rst              # All modules overview
│   ├── database.rst             # Database module
│   ├── input.rst                # Input module
│   ├── processing.rst           # Processing module
│   ├── signals.rst              # Signals module
│   ├── output.rst               # Output module
│   └── storage.rst              # Storage module
├── _static/                     # Static files (CSS, images)
├── _build/                      # Generated HTML (output)
└── _templates/                  # Custom Jinja templates (optional)
```

## Writing Documentation

### Adding Docstrings to Code
All modules, classes, and functions include comprehensive docstrings using Google/Numpy style:

```python
def calculate_var_95(returns, window=252, confidence=0.95):
    """
    Calculate Value-at-Risk at 95% confidence level.
    
    Args:
        returns: Series or array of returns
        window: Rolling window size in days (default: 252)
        confidence: Confidence level (default: 0.95)
    
    Returns:
        float: VAR value as percentage
    
    Raises:
        ValueError: If window is larger than data length
    
    Example:
        >>> returns = pd.Series([0.01, -0.02, 0.015, ...])
        >>> var = calculate_var_95(returns, window=252)
    """
```

### Creating New Documentation Pages
1. Create `.rst` file in `docs/` directory
2. Add to appropriate section in `docs/index.rst` toctree
3. Use reStructuredText format with proper markup
4. Rebuild HTML with `sphinx-build`

## Sphinx Extensions

The documentation uses these Sphinx extensions:
- **sphinx.ext.autodoc**: Auto-generate documentation from docstrings
- **sphinx.ext.napoleon**: Support Google/Numpy docstring style
- **sphinx.ext.viewcode**: Show source code links
- **sphinx.ext.intersphinx**: Link to external documentation

## Theme

The documentation uses the **Read the Docs theme** (sphinx-rtd-theme) for professional appearance.

## Configuration

Key Sphinx settings in `conf.py`:
- **Project**: Investment Strategy Data Pipeline v2.0.0
- **Language**: English
- **Theme**: sphinx_rtd_theme
- **Extensions**: autodoc, napoleon, viewcode, intersphinx
- **Autodoc Options**: Include all members, show inheritance

## Maintaining Documentation

### When Adding New Features
1. Add comprehensive docstring to code
2. Update relevant `.rst` file or create new one
3. Rebuild HTML documentation
4. Test links and rendering

### When Changing Architecture
1. Update `architecture.rst` with new diagrams
2. Update `api/modules.rst` if module structure changed
3. Update relevant API reference files
4. Rebuild and verify links work

### When Fixing Bugs
1. Document solution in `troubleshooting.rst`
2. Update `faq.rst` if frequently asked
3. Add example to relevant usage section

## Troubleshooting Documentation Build

**Build Error: "Could not import extension..."**
- Ensure all dependencies installed: `poetry install`
- Check Sphinx version: `poetry run sphinx-build --version`

**Build Warning: "Undefined reference..."**
- Check `.rst` file for typos in cross-references
- Rebuild with verbose output: `sphinx-build -v -b html . _build/html`

**Documentation Not Updating**
- Delete old build: `rm -rf _build/`
- Rebuild fresh: `poetry run sphinx-build -b html . _build/html`

## Publishing Documentation

### GitHub Pages
1. Build HTML: `sphinx-build -b html . _build/html`
2. Push `_build/html` to `gh-pages` branch
3. Enable GitHub Pages in repository settings

### Read the Docs
1. Create account at readthedocs.org
2. Import repository
3. Configure build settings
4. Automatic builds on git push

## Documentation Statistics

- **Total Pages**: 16 (.rst files)
- **API Classes Documented**: 15+
- **Code Examples**: 50+
- **External Links**: Comprehensive
- **Generated HTML**: ~100 pages

## Quick Links

- **Main Documentation**: `_build/html/index.html`
- **Installation Guide**: `_build/html/installation.html`
- **API Reference**: `_build/html/api/index.html`
- **Troubleshooting**: `_build/html/troubleshooting.html`

## Support

For documentation issues:
1. Check `troubleshooting.rst` and `faq.rst`
2. Review source `.rst` files for context
3. Verify Python code against API reference
4. Run tests to validate examples
