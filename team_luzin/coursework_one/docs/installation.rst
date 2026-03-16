Installation Guide
===================

Prerequisites
-------------

Before installing the Investment Strategy Data Pipeline, ensure you have:

- **Python 3.10 or higher**: `python --version`
- **Poetry** (Python dependency manager): `pip install poetry`
- **PostgreSQL 12+**: For structured data storage
- **MongoDB 4.4+**: For document storage (optional)
- **MinIO**: For data lake (optional, or use S3-compatible storage)
- **Git**: For version control

System Requirements
~~~~~~~~~~~~~~~~~~~

- **Operating System**: macOS, Linux, or Windows (WSL2)
- **Memory**: Minimum 8GB RAM (16GB recommended)
- **Disk Space**: 20GB for database and MinIO storage
- **Python**: 3.10 or newer

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

    database:
      host: localhost
      port: 5439
      user: postgres
      password: postgres
      database: fift
      schema: systematic_equity

    minio:
      endpoint: localhost:9000
      access_key: minioadmin
      secret_key: minioadmin
      bucket: investment-data
      secure: false

    mongodb:
      host: localhost
      port: 27019
      database: investment_data

    logging:
      level: INFO
      file: logs/pipeline.log

**Important**: Add ``config/conf.yaml`` to ``.gitignore`` to protect credentials.

Step 4: Docker Setup (Optional)
-------------------------------

To run PostgreSQL, MongoDB, and MinIO in Docker:

.. code-block:: bash

    # From repository root
    docker compose up -d postgres_db mongo_db minio

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
