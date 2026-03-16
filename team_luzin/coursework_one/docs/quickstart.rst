Quick Start Guide
=================

5-Minute Setup
--------------

Get the pipeline running in under 5 minutes:

.. code-block:: bash

    # 1. Clone and navigate
    git clone https://github.com/iftucl/ift_coursework_2025.git
    cd team_luzin/coursework_one

    # 2. Install dependencies
    poetry install

    # 3. Start services (from repo root)
    cd ../..
    docker compose up -d postgres_db

    # 4. Configure database
    cd team_luzin/coursework_one
    cat > config/conf.yaml << 'EOF'
    database:
      host: localhost
      port: 5439
      user: postgres
      password: postgres
      database: fift
      schema: systematic_equity
    EOF

    # 5. Run pipeline
    poetry run python3 main.py --dry-run

Your First Pipeline Run
-----------------------

Basic execution:

.. code-block:: bash

    # Test run (no database writes)
    poetry run python3 main.py --dry-run

    # Full pipeline with daily frequency
    poetry run python3 main.py --frequency daily

    # Full pipeline with specific date
    poetry run python3 main.py --run-date 2026-03-08

    # Monthly analysis
    poetry run python3 main.py --frequency monthly

Understanding the Output
~~~~~~~~~~~~~~~~~~~~~~~~

The pipeline produces:

1. **Step 1 - VAR Calculation**
   - Computes Value-at-Risk (95th percentile) for each stock
   - Calculates 14-day Average True Range (ATR)
   - Filters to 597 eligible stocks

2. **Step 2 - Portfolio Selection**
   - Selects top 130 stocks by composite score
   - Combines risk, momentum, and liquidity metrics
   - Exports to PostgreSQL

3. **Step 3 - Signal Generation**
   - Generates trading signals using MACD and ATR
   - Identifies BUY/SELL opportunities
   - Creates 335 executable signals

4. **Step 4 - Data Export**
   - Exports results to MinIO
   - Generates analytics summaries
   - Stores execution records

Expected Results
~~~~~~~~~~~~~~~~

For a complete pipeline run:

.. code-block:: text

    ✓ Step 1: VAR calculation completed
      - 678 stocks processed
      - 597 stocks calculated (88.1%)
      - Results: VaR_95, ATR_14

    ✓ Step 2: Portfolio selection completed
      - 130 stocks selected (19.2%)
      - Composite score calculated
      - Results: COMPOSITE_SCORE, RANKING

    ✓ Step 3: Signal generation completed
      - 335 signals generated
      - Signal types: BUY (49.4%), SELL (remaining)
      - Results: SIGNAL_TYPE, STRENGTH

    ✓ Step 4: Analytics export completed
      - Data exported to MinIO
      - Summary reports generated
      - Execution records stored

Common Commands
---------------

**Daily Updates**

.. code-block:: bash

    # Run daily update
    poetry run python3 main.py --frequency daily

**Dry Run (No Database Changes)**

.. code-block:: bash

    # Test entire pipeline without persisting
    poetry run python3 main.py --dry-run --frequency monthly

**Specific Date Analysis**

.. code-block:: bash

    # Analyze data as of specific date
    poetry run python3 main.py --run-date 2026-02-15

**View Help**

.. code-block:: bash

    # Show all available options
    poetry run python3 main.py --help

Configuration Options
---------------------

Modify ``config/conf.yaml`` to customize behavior:

**Data Sources**

.. code-block:: yaml

    data:
      start_date: 2021-01-01
      end_date: 2026-03-08
      universe: sp500_russell1000
      frequency: daily

**Processing Parameters**

.. code-block:: yaml

    processing:
      var_window: 252                    # 1-year VAR
      atr_period: 14                     # 14-day ATR
      momentum_period: 20                # 20-day momentum
      min_liquidity: 1000000             # Minimum daily volume

**Output Settings**

.. code-block:: yaml

    output:
      format: parquet                    # parquet or csv
      compression: snappy
      include_intermediate: false        # Include step outputs

**Database**

.. code-block:: yaml

    database:
      host: localhost
      port: 5439
      user: postgres
      password: postgres
      database: fift
      schema: systematic_equity
      pool_size: 10
      timeout: 30

Running Tests
-------------

Verify the installation works correctly:

.. code-block:: bash

    # Run all tests
    poetry run pytest

    # Run with coverage report
    poetry run pytest --cov=modules --cov-report=html

    # Run specific test file
    poetry run pytest test/test_risk.py -v

    # Run specific test
    poetry run pytest test/test_risk.py::TestRiskCalculator::test_var_95 -v

Accessing Documentation
-----------------------

**Build HTML Documentation**

.. code-block:: bash

    cd docs
    poetry run sphinx-build -b html . _build/html

    # Open in browser
    open _build/html/index.html  # macOS
    xdg-open _build/html/index.html  # Linux

**View API Documentation**

.. code-block:: bash

    # Generate API docs
    poetry run sphinx-apidoc -f -o docs/api modules

    # Build HTML
    cd docs && poetry run sphinx-build -b html . _build/html

Next Steps
----------

After your first run:

1. :doc:`Explore Configuration <configuration>` options
2. :doc:`Review Architecture <architecture>` design
3. :doc:`Check API Reference <api/index>` for detailed functions
4. :doc:`Read Usage Guide <usage>` for advanced features

Troubleshooting Quick Runs
--------------------------

**Database Connection Error**

.. code-block:: bash

    # Check PostgreSQL is running
    docker compose ps postgres_db

    # Verify config/conf.yaml has correct credentials
    cat config/conf.yaml | grep -A 5 database:

**Missing Dependencies**

.. code-block:: bash

    # Reinstall with Poetry
    poetry install --no-cache

**Slow Performance**

- Increase allocated memory (default 8GB recommended)
- Check PostgreSQL connection pool size
- Verify MinIO is running if exporting data

**Debug Output**

.. code-block:: bash

    # Enable verbose logging
    LOGLEVEL=DEBUG poetry run python3 main.py --dry-run
