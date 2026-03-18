Architecture Overview
=====================

System Design
-------------

The Investment Strategy Data Pipeline implements a modular, sequential processing architecture with four distinct stages:

.. code-block:: text

    Data Sources (yfinance, PostgreSQL)
              │
              ▼
    ┌─────────────────────┐
    │ Step 1: Risk Metrics│ (VAR-95, ATR-14)
    └──────────┬──────────┘
              │
              ▼
    ┌─────────────────────┐
    │ Step 2: Portfolio   │ (Composite Scoring)
    │ Selection           │
    └──────────┬──────────┘
              │
              ▼
    ┌─────────────────────┐
    │ Step 3: Signals     │ (MACD, ATR, Filters)
    └──────────┬──────────┘
              │
              ▼
    ┌─────────────────────┐
    │ Step 4: Export &    │ (PostgreSQL, MinIO)
    │ Storage             │
    └─────────────────────┘

Each stage produces intermediate results (CSV/Parquet files) that feed into the next stage. This modular design simplifies testing, debugging, and future extension.

**Output Variability:** The number of securities, selected stocks, and signals produced depend on:
- Data availability from yfinance for the specified date range
- Data quality (missing values, trading halts)
- Risk filter thresholds and ranking criteria
- Technical indicator parameters and signal confirmation rules

Core Components
---------------

**Module: modules/db/**

Database connectivity for PostgreSQL operations:

.. code-block:: text

    modules/db/
    ├── __init__.py
    └── postgres_connector.py    # Connection pooling and queries

Key Class:
- ``PostgresConnector``: Manages database connections and result persistence

**Module: modules/input/**

Data ingestion and loading:

.. code-block:: text

    modules/input/
    ├── __init__.py
    └── market_data_loader.py    # OHLCV data from yfinance

Key Class:
- ``MarketDataLoader``: Retrieves historical price data and company reference data

**Module: modules/processing/**

Risk metrics, momentum, and factor calculations:

.. code-block:: text

    modules/processing/
    ├── __init__.py
    ├── risk.py                  # VAR-95, ATR-14 calculations
    ├── momentum.py              # Returns and momentum metrics
    ├── liquidity.py             # Volume and spread analysis
    ├── composite_score.py       # Multi-factor ranking
    ├── sector_analysis.py       # Sector diversification
    └── trend.py                 # Trend and momentum indicators

Key Classes:
- ``RiskCalculator``: Computes VAR (95th percentile loss) and ATR (volatility)
- ``MomentumCalculator``: Calculates returns over multiple periods
- ``LiquidityCalculator``: Analyzes trading volume and spreads
- ``CompositeScorer``: Ranks securities using multi-factor weighted scoring
- ``TrendAnalyzer``: Identifies trend direction and strength

**Module: modules/signals/**

Trading signal generation and validation:

.. code-block:: text

    modules/signals/
    ├── __init__.py
    ├── execution_signals.py     # MACD and signal generation
    ├── signal_strength.py       # Confidence scoring
    └── signal_filter.py         # Signal filtering and validation

Key Classes:
- ``ExecutionSignalGenerator``: Generates BUY/SELL/HOLD using MACD and ATR
- ``SignalStrengthCalculator``: Scores signal reliability
- ``SignalFilter``: Applies filtering criteria

**Module: modules/output/**

Results export to multiple formats:

.. code-block:: text

    modules/output/
    ├── __init__.py
    ├── export_analytics.py      # CSV/Parquet export
    └── results_exporter.py      # (if present)

Key Classes:
- ``ResultsExporter`` and ``AnalyticsGenerator``: Handle multi-format output

**Module: modules/storage/**

Cloud and persistent storage:

.. code-block:: text

    modules/storage/
    ├── __init__.py
    ├── minio_storage.py         # MinIO S3-compatible uploads
    └── datalake_writer.py       # Data lake organization

Key Classes:
- ``MinIOStorage``: Handles optional uploads to MinIO
- ``DataLakeWriter``: Organizes exports in cloud storage

Pipeline Execution
------------------

The pipeline is executed through:
- ``main.py``: Official coursework entry point (thin wrapper)
- ``run_pipeline.py``: Core orchestration engine with CLI argument parsing
- ``pipeline/`` directory: Individual step scripts

**Step 1: Risk Calculation** (``pipeline/calculate_var_all_stocks.py``)

Loads data from PostgreSQL and yfinance:
- Fetches company universe from ``systematic_equity.company_static`` table
- Retrieves 5-year historical OHLCV data via yfinance
- Calculates VAR-95 (95th percentile loss) with 252-day rolling window
- Calculates ATR-14 (14-period average true range as % of close price)
- Outputs: CSV/Parquet with risk metrics for all eligible securities

**Step 2: Portfolio Selection** (``pipeline/calculate_composite_portfolio.py``)

Ranks and selects securities:
- Computes momentum scores (returns over 1, 5, 20, 60 days)
- Computes liquidity scores (volume and bid-ask spread proxies)
- Computes composite score combining risk, momentum, liquidity, and sector balance
- Performs sector diversification to ensure broad exposure
- Outputs: CSV/Parquet with selected securities and scores

**Step 3: Signal Generation** (``pipeline/trading_execution.py``)

Generates trading signals for selected securities:
- Calculates MACD (12-day, 26-day, 9-day signal line)
- Generates initial signals (positive MACD = BUY, negative = SELL, near-zero = HOLD)
- Filters by ATR confirmation (reduces false signals in low-volatility periods)
- Applies strength scoring and additional validation
- Outputs: CSV/Parquet with signals and metadata

**Step 4: Export & Storage** (``pipeline/export_analytics_to_minio.py``)

Persists results:
- Stores portfolio selections in PostgreSQL (``systematic_equity.portfolio_selections`` table)
- Stores signals in PostgreSQL (``systematic_equity.trading_signals`` table)
- Exports analytics to local filesystem (CSV and Parquet files)
- Optionally uploads to MinIO if configured (``MINIO_REQUIRED`` environment variable)
- Reports status: ✅ (both backends), ⚠️ (local only), or ❌ (if MinIO required but failed)

Key Metrics
-----------

**Value-at-Risk (VAR-95)**

Calculated as the 95th percentile of daily returns over a 252-day window:

$$\text{VAR}_{95} = \text{quantile}(\text{daily\_returns}, 0.05)$$

Measured in percentage terms. Used to identify risky securities and confirm trade validity.

**Average True Range (ATR-14)**

Normalized volatility metric over 14 days:

$$\text{ATR\%} = \frac{\text{ATR}_{14}}{\text{Close Price}} \times 100$$

Used to filter signals and scale position sizing in realistic trading scenarios.

**Composite Score**

Multi-factor ranking using weighted combination:

$$\text{Score} = w_1 \cdot M + w_2 \cdot L + w_3 \cdot T - w_4 \cdot R$$

Where M = momentum, L = liquidity, T = trend, R = risk. Weights determined by configuration.

**MACD Signal**

Technical momentum indicator:

- MACD Line = EMA(close, 12) - EMA(close, 26)
- Signal Line = EMA(MACD, 9)
- Histogram = MACD - Signal

BUY signals when MACD crosses above Signal; SELL when below; HOLD otherwise.

Data Storage
------------

**PostgreSQL** (Primary Persistent Store)

Structured tables in the ``systematic_equity`` schema:

- ``company_static``: Reference data (symbol, sector, industry, country)
- ``portfolio_selections``: Selected securities with scores and rankings
- ``trading_signals``: Generated signals with strength, dates, and indicator values

**Local Filesystem** (Analytics Outputs)

Export directory (``analytics/processed/stepN/``) contains:

- Step 1: ``factors_latest.csv|parquet`` — risk metrics for all securities
- Step 2: ``selections_latest.csv|parquet`` — selected portfolio with scores
- Step 3: ``signals_latest.csv|parquet`` — trading signals with metadata
- Step 4: Summary statistics and logs

**MinIO** (Optional Cloud Storage)

S3-compatible object storage (if configured):

- Mirrored data lake structure for backup and archival
- Configurable via environment variables (``MINIO_ENDPOINT``, ``MINIO_ACCESS_KEY``, etc.)
- Optional by default; can be made mandatory with ``MINIO_REQUIRED=true``
- Graceful degradation: pipeline continues if MinIO unavailable (unless required)

Configuration
-------------

Pipeline behavior is controlled via:

1. **CLI Arguments** (via ``main.py``)
   - ``--frequency``: daily, weekly, monthly, quarterly
   - ``--run-date``: specific YYYY-MM-DD for historical analysis
   - ``--dry-run``: execute without database writes

2. **config/conf.yaml** (Database and Processing Parameters)
   - PostgreSQL connection settings
   - Risk window sizes (VAR: 252 days, ATR: 14 days)
   - Momentum periods [1, 5, 20, 60]
   - Output format (CSV or Parquet)

3. **Environment Variables** (Storage Integration)
   - ``MINIO_ENDPOINT``, ``MINIO_ACCESS_KEY``, ``MINIO_SECRET_KEY``: MinIO credentials
   - ``MINIO_BUCKET``, ``MINIO_SECURE``: MinIO configuration
   - ``MINIO_REQUIRED``: true/false (fail if MinIO unavailable)

Design Rationale
----------------

**Sequential Pipeline:**
Clear separation of concerns and data dependency. Each stage is independently testable.

**Modular Processing:**
Risk, momentum, liquidity, and signal calculations are in separate, reusable modules.
New metrics can be added without modifying pipeline orchestration.

**Multi-Format Output:**
CSV for human inspection; Parquet for efficient storage and analytics.
PostgreSQL for operational queries; MinIO for optional archival.

**Optional MinIO:**
Local development works without cloud setup. Production deployments can enable cloud backup
with graceful failure handling.

**Configuration-Driven:**
Thresholds (VAR limits, ATR floors), weights, and parameters are externalized
to support multiple strategy variants from shared code.

Limitations & Future Work
--------------------------

**Current Scope:**
- Designed for 600+ equities with daily data
- Single-factor (equity) asset class
- Post-trade analysis only; no pre-trade optimization
- Historical analysis based on past signals (not forward-looking)

**Possible Extensions:**
- Real-time signal generation (streaming data)
- Multi-asset support (bonds, commodities, forex)
- Advanced portfolio construction (Markowitz, Black-Litterman)
- Machine learning-based signal refinement
- Cross-asset correlation analysis

**Known Constraints:**
- yfinance data quality dependent on data availability
- Sector analysis limited to GICS classification
- MACD settings fixed (12, 26, 9); not adaptive to market regime
- No slippage or transaction cost modeling

