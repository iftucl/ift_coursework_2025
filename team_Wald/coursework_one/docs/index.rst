Value + News Sentiment Strategy — Documentation
=================================================

**UCL Institute of Finance & Technology — IFTE0003: Big Data in Quantitative Finance**

**Team 09 — Coursework 1**

This documentation covers the complete data pipeline for the Value + News Sentiment
equity investment strategy. The pipeline processes 678 companies across 8 countries,
extracting financial data and news articles to construct a composite investment signal.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

Overview
========

The strategy combines two complementary investment factors:

* **Value Factor (60% weight)**: Identifies undervalued companies using percentile-rank
  scoring of P/E, P/B, EV/EBITDA, and Dividend Yield ratios from Yahoo Finance.
* **Sentiment Factor (40% weight)**: Filters value traps using VADER NLP sentiment
  analysis of news headlines and descriptions from GDELT and Yahoo Finance.

The composite formula is: ``Composite Score = 0.6 x Value Score + 0.4 x Sentiment Score``

Companies must pass all filters:

* Debt/Equity < 2.0 (not over-leveraged)
* Average Sentiment > 0.0 (net positive news)
* Minimum 3 articles for reliable sentiment

The top 20% (top quintile) are flagged with ``invest_decision = True`` for CW2.

Installation
============

Prerequisites
-------------

* Python 3.10 or newer
* Docker and Docker Compose
* Poetry (Python package manager)

Step-by-Step Setup
------------------

1. Clone and navigate to the project::

    git clone https://github.com/YOUR-USERNAME/ift_coursework_2025.git
    cd ift_coursework_2025/team_09/coursework_one

2. Start the Docker infrastructure::

    docker compose up -d
    docker compose ps   # Verify all services are running

3. Install Python dependencies::

    poetry install

4. Set up environment variables::

    cp .env.example .env.dev

5. Verify the installation::

    poetry run pytest ./test/ -v --cov=modules

Usage
=====

Basic Execution
---------------

Run the pipeline with different frequencies::

    # Weekly run (default)
    poetry run python Main.py --env_type dev --frequency weekly

    # Daily incremental update
    poetry run python Main.py --env_type dev --frequency daily

    # Monthly full refresh
    poetry run python Main.py --env_type dev --frequency monthly

    # Quarterly with schema re-creation
    poetry run python Main.py --env_type dev --frequency quarterly --init_schema

Advanced Options
----------------

::

    # Run only specific data sources
    poetry run python Main.py --env_type dev --sources prices news

    # Process specific tickers
    poetry run python Main.py --env_type dev --tickers AAPL MSFT GOOGL

    # Custom batch size
    poetry run python Main.py --env_type dev --batch_size 25

    # Validate configuration without downloading
    poetry run python Main.py --env_type dev --dry_run

    # Backfill for a specific date
    poetry run python Main.py --env_type dev --run_date 2024-06-15

Command-Line Arguments
----------------------

.. list-table::
   :header-rows: 1

   * - Argument
     - Default
     - Description
   * - ``--env_type``
     - (required)
     - Environment: ``dev`` or ``docker``
   * - ``--frequency``
     - ``weekly``
     - Run frequency: ``daily``, ``weekly``, ``monthly``, ``quarterly``
   * - ``--lookback_years``
     - 5
     - Historical data lookback: ``2``, ``5``, ``6``, or ``10`` years
   * - ``--run_date``
     - Today
     - Specific date (YYYY-MM-DD)
   * - ``--sources``
     - All
     - Data sources: ``prices``, ``financials``, ``news``, ``fx``
   * - ``--tickers``
     - All 678
     - Specific ticker symbols
   * - ``--batch_size``
     - 50
     - Companies per processing batch
   * - ``--init_schema``
     - False
     - Re-create database tables
   * - ``--dry_run``
     - False
     - Validate config and exit

Architecture
============

Pipeline Flow
-------------

The pipeline follows an Extract-Transform-Load (ETL) pattern:

1. **Extract**: Yahoo Finance (prices, ratios, financials), GDELT (news), FX rates
2. **Store Raw**: MinIO (data lake for CSV/JSON), MongoDB (document store for articles)
3. **Transform**: Data cleaning, VADER sentiment scoring, percentile-rank value scoring
4. **Load Clean**: PostgreSQL (structured analytics tables with upsert support)
5. **Composite**: Combine value + sentiment, apply filters, rank, flag for investment
6. **Events**: Publish to Kafka topics (news-articles, value-metrics) for downstream consumers

Infrastructure Components
-------------------------

.. list-table::
   :header-rows: 1

   * - System
     - Role
     - Contents
   * - PostgreSQL 16
     - Relational analytics store
     - 8 tables: prices, value metrics, sentiment scores, composite rankings, FX rates, audit logs
   * - MongoDB 7.0
     - Document store
     - Raw news articles, financial data JSON, API responses
   * - MinIO
     - S3-compatible data lake
     - Raw CSV/JSON files for full lineage and reproducibility
   * - Apache Kafka
     - Event streaming
     - News article and value metric events for decoupled processing

Database Schema
---------------

All tables are in the ``systematic_equity`` schema within the ``fift`` database:

* ``company_static`` — 678-company investable universe (symbol, name, sector, country)
* ``daily_prices`` — 5-year daily OHLCV with currency (PK: symbol, cob_date)
* ``value_metrics`` — P/E, P/B, EV/EBITDA, Dividend Yield, D/E, Value Score (UNIQUE: company_id, date)
* ``sentiment_scores`` — VADER aggregated scores per company (UNIQUE: company_id, date)
* ``composite_rankings`` — Final score, rank, invest_decision (UNIQUE: company_id, date)
* ``fx_rates`` — Daily exchange rates for 4 currency pairs (PK: currency_pair, cob_date)
* ``ingestion_log`` — Full pipeline audit trail with run_id, source, status, error messages
* ``pipeline_metadata`` — Tracks last successful run per source/ticker

Testing
=======

The project achieves **93% test coverage** across **281 tests** (target: 80%+)::

    # Run full test suite
    poetry run pytest ./test/ -v --cov=modules --cov-report=term-missing

    # Run only unit tests
    poetry run pytest ./test/ -v -m "not integration"

    # Generate HTML coverage report
    poetry run pytest ./test/ --cov=modules --cov-report=html

Code Quality
============

::

    # Linting (must pass with 0 errors)
    poetry run flake8 modules/ Main.py --max-line-length=120

    # Formatting
    poetry run black modules/ Main.py test/ --line-length 120

    # Import sorting
    poetry run isort modules/ Main.py test/ --profile black

    # Security scanning
    poetry run bandit -r modules/ -c pyproject.toml

API Reference
=============

Extraction Modules
------------------

.. automodule:: modules.extraction.company_loader
   :members:
   :undoc-members:

.. automodule:: modules.extraction.yahoo_finance_extractor
   :members:
   :undoc-members:

.. automodule:: modules.extraction.gdelt_extractor
   :members:
   :undoc-members:

.. automodule:: modules.extraction.fx_extractor
   :members:
   :undoc-members:

Processing Modules
------------------

.. automodule:: modules.processing.value_scorer
   :members:
   :undoc-members:

.. automodule:: modules.processing.sentiment_scorer
   :members:
   :undoc-members:

.. automodule:: modules.processing.composite_scorer
   :members:
   :undoc-members:

.. automodule:: modules.processing.data_cleaner
   :members:
   :undoc-members:

Database Modules
----------------

.. automodule:: modules.db.postgres_connection
   :members:
   :undoc-members:

.. automodule:: modules.db.mongo_connection
   :members:
   :undoc-members:

.. automodule:: modules.db.minio_connection
   :members:
   :undoc-members:

Loading Modules
---------------

.. automodule:: modules.loading.postgres_loader
   :members:
   :undoc-members:

.. automodule:: modules.loading.mongo_loader
   :members:
   :undoc-members:

.. automodule:: modules.loading.minio_uploader
   :members:
   :undoc-members:

Kafka Module
------------

.. automodule:: modules.kafka.kafka_handler
   :members:
   :undoc-members:

Utility Modules
---------------

.. automodule:: modules.utils.config_reader
   :members:
   :undoc-members:

.. automodule:: modules.utils.logger
   :members:
   :undoc-members:

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
