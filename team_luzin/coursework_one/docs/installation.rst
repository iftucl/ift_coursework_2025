Installation Guide
===================

Prerequisites
-------------

Before installing the Investment Strategy Data Pipeline, ensure you have:

- **Python 3.9 or higher**: `python --version`
- **Poetry** (Python dependency manager): `pip install poetry`
- **PostgreSQL 12+**: For structured data storage
- **MinIO**: For cloud data lake storage (S3-compatible)
- **Git**: For version control

System Requirements
~~~~~~~~~~~~~~~~~~~

- **Operating System**: macOS, Linux, or Windows (WSL2)
- **Memory**: Minimum 8GB RAM (16GB recommended)
- **Disk Space**: 20GB for database and MinIO storage
- **Python**: 3.9 or newer

Step 1: Clone the Repository
-----------------------------

.. code-block:: bash

    git clone https://github.com/iftucl/ift_coursework_2025.git
    cd ift_coursework_2025/team_luzin/coursework_one

Step 2: Set Up Python Virtual Environment
------------------------------------------

Using Poetry (recommended):

.. code-block:: bash

    # Install dependencies using Poetry
    poetry install

    # Activate the virtual environment
    poetry shell

Alternative with venv:

.. code-block:: bash

    # Create virtual environment
    python3 -m venv .venv
    source .venv/bin/activate  # On Windows: .venv\Scripts\activate

    # Install dependencies
    pip install -r requirements.txt

Step 3: Configure Database Connections
---------------------------------------

Create a ``config/conf.yaml`` file with your database credentials:

.. code-block:: yaml

    postgres:
      host: localhost
      port: 5439
      user: postgres
      password: postgres
      database: fift
      schema: systematic_equity

    minio:
      endpoint: localhost:9000
      access_key: ift_bigdata
      secret_key: minio_password
      bucket: csreport
      use_ssl: false

    pipeline:
      run_frequency: daily
      historical_years: 5

**Important**: Add ``config/conf.yaml`` to ``.gitignore`` to protect credentials.

Step 4: Docker Setup (Optional)
-------------------------------

To run PostgreSQL, MongoDB, and MinIO in Docker:

.. code-block:: bash

    # From repository root
    docker compose up -d postgres_db minio

    # Verify services are running
    docker compose ps

Database initialization:

.. code-block:: bash

    # Initialize PostgreSQL schema
    docker compose exec postgres_db psql -U postgres -d fift -f /create_tables.sql

Step 5: Verify Installation
----------------------------

Test that everything is working:

.. code-block:: bash

    # Test Python environment
    poetry run python3 -c "import pandas as pd; print('✓ Dependencies OK')"

    # Test database connection
    poetry run python3 << 'EOF'
    import psycopg2
    conn = psycopg2.connect(
        host='localhost',
        port=5439,
        user='postgres',
        password='postgres',
        database='fift'
    )
    print('✓ PostgreSQL connection OK')
    conn.close()
    EOF

    # Run dry-run test
    poetry run python3 main.py --dry-run --frequency monthly

Troubleshooting Installation
-----------------------------

PostgreSQL Connection Failed
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # Check if PostgreSQL is running
    docker compose ps postgres_db

    # View logs
    docker compose logs postgres_db

    # Restart service
    docker compose restart postgres_db

Missing Dependencies
~~~~~~~~~~~~~~~~~~~~

If you encounter missing packages:

.. code-block:: bash

    # Update Poetry lock file
    poetry update

    # Reinstall all dependencies
    poetry install --no-cache

    # Clear Python cache
    find . -type d -name __pycache__ -exec rm -rf {} +

Python Version Mismatch
~~~~~~~~~~~~~~~~~~~~~~~

Verify Python version and update if needed:

.. code-block:: bash

    python3 --version  # Should be 3.10+
    poetry env use python3.10  # If multiple versions installed

Development Setup
-----------------

For development, install additional tools:

.. code-block:: bash

    # Install with all optional dependencies
    poetry install --with dev

    # Install pre-commit hooks (optional)
    pip install pre-commit
    pre-commit install

Building Documentation
----------------------

This project uses Sphinx to generate HTML documentation automatically from reStructuredText source files and code docstrings.

**Generate HTML Documentation:**

.. code-block:: bash

    # From the coursework_one directory
    poetry run sphinx-build -b html docs/ docs/_build/html

**View Generated Documentation:**

.. code-block:: bash

    # Open in browser
    open docs/_build/html/index.html  # macOS
    xdg-open docs/_build/html/index.html  # Linux

    # Or serve locally to test
    python3 -m http.server --directory docs/_build/html 8000
    # Then visit http://localhost:8000 in your browser

The HTML documentation is built from:
- **RST source files** in ``docs/`` (installation, quickstart, architecture, usage, etc.)
- **Module docstrings** automatically extracted via Sphinx autodoc from Python source code
- **API reference** auto-generated from docstrings in ``modules/`` directory

**Rebuild after code changes:**

.. code-block:: bash

    # Clean build to ensure all changes are included
    rm -rf docs/_build
    poetry run sphinx-build -b html docs/ docs/_build/html

Next Steps
----------

After installation:

1. Review the :doc:`Configuration <configuration>` guide
2. Run the :doc:`Quick Start <quickstart>` tutorial
3. Explore the :doc:`Architecture <architecture>` overview
4. Consult the :doc:`API Reference <api/index>` for detailed usage

Support
-------

For issues:

1. Check the :doc:`Troubleshooting <troubleshooting>` guide
2. Review :doc:`FAQ <faq>`
3. Check application logs in ``logs/`` directory
4. Open an issue on GitHub (if applicable)
