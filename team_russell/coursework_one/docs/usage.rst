Usage Instructions
==================

All commands below are run from ``team_russell/coursework_one/``.

Pipeline A — Data Ingestion
----------------------------

Pipeline A fetches daily prices and annual financials for all companies in the
investable universe and publishes the raw data to Kafka and MinIO.

.. code-block:: bash

   # Fetch prices and financials for all 678 companies (default: 5-year lookback)
   poetry run python a_pipeline/main.py --mode all --lookback-years 5

   # Prices only
   poetry run python a_pipeline/main.py --mode prices

   # Financials only (Yahoo Finance, default)
   poetry run python a_pipeline/main.py --mode financials

   # Financials from Alpha Vantage (requires API key in conf.yaml)
   poetry run python a_pipeline/main.py --mode financials \
       --financial-source alphavantage

**Arguments:**

``--mode``
    ``all`` | ``prices`` | ``financials`` — controls which data to fetch.

``--lookback-years``
    Number of years of price history to retrieve (default: 5).

``--financial-source``
    ``yfinance`` (default) | ``alphavantage``.

``--run-date``
    Reference date for the run (default: today). Format ``YYYY-MM-DD``.

Pipeline B — Processing and Storage
-------------------------------------

Pipeline B is a long-lived Kafka consumer that transforms raw messages and
writes them to MongoDB (raw store) and PostgreSQL (structured store).
Run it **concurrently** with Pipeline A.

.. code-block:: bash

   poetry run python b_pipeline/main.py

   # Custom poll timeout (seconds, default: 1.0)
   poetry run python b_pipeline/main.py --poll-timeout 5

Stop with ``Ctrl+C`` once Pipeline A has finished.

Pipeline C — Factor Computation
---------------------------------

Pipeline C reads structured data from PostgreSQL, computes the 8-metric
Value + Quality composite factor, and writes results back to
``systematic_equity.factor_values``.

Run once per rebalance date (yearly):

.. code-block:: bash

   poetry run python c_pipeline/main.py --run-date 2022-12-31
   poetry run python c_pipeline/main.py --run-date 2023-12-31
   poetry run python c_pipeline/main.py --run-date 2024-12-31
   poetry run python c_pipeline/main.py --run-date 2025-12-31

**Arguments:**

``--run-date``
    Rebalance date in ``YYYY-MM-DD`` format (default: today).
    Financial data is automatically lagged by 3 months to prevent
    look-ahead bias.

Running the Test Suite
-----------------------

Tests are organised per pipeline and must be run from each pipeline's
root directory (each pipeline has its own ``modules`` namespace):

.. code-block:: bash

   cd a_pipeline && python -m pytest test/ -v   # 39 tests  (88% coverage)
   cd b_pipeline && python -m pytest test/ -v   # 37 tests  (97% coverage)
   cd c_pipeline && python -m pytest test/ -v   # 68 tests  (98% coverage)

Total: **144 tests, 0 failures, ~94% average coverage**.

To generate a coverage report:

.. code-block:: bash

   cd a_pipeline && python -m pytest test/ --cov=modules --cov-report=html

Open ``a_pipeline/htmlcov/index.html`` to view the HTML coverage report.

Code Quality Checks
-------------------

.. code-block:: bash

   python -m flake8 .          # PEP 8 linting
   python -m black --check .   # formatting
   python -m isort --check .   # import ordering
   python -m bandit -r . -q    # security scan
