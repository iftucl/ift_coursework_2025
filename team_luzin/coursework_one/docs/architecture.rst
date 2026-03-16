Architecture Overview
=====================

System Architecture
-------------------

The Investment Strategy Data Pipeline follows a modular, multi-stage architecture:

.. code-block:: text

    ┌─────────────────────────────────────────────────────────────┐
    │                  Data Sources                                │
    │  (yfinance, market feeds, reference data)                   │
    └────────────────────────┬────────────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │  Step 1: Risk   │
                    │  Calculation    │
                    │  (VAR, ATR)     │
                    └────────┬────────┘
                             │ 597 stocks
                    ┌────────▼──────────────┐
                    │ Step 2: Portfolio     │
                    │ Selection             │
                    │ (Composite Score)     │
                    └────────┬──────────────┘
                             │ 130 stocks
                    ┌────────▼──────────────┐
                    │ Step 3: Signal        │
                    │ Generation            │
                    │ (MACD, ATR, Liquidity)│
                    └────────┬──────────────┘
                             │ 335 signals
                    ┌────────▼──────────────┐
                    │ Step 4: Export &      │
                    │ Storage               │
                    │ (DB, MinIO, MongoDB)  │
                    └────────┬──────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
    ┌───▼───┐         ┌──────▼──────┐      ┌─────▼──────┐
    │PostgreSQL       │   MinIO     │      │  MongoDB   │
    │Structured      │   (S3-like) │      │  Documents │
    │Data Store      │   Data Lake │      │            │
    └────────┘       └─────────────┘      └────────────┘

Core Components
---------------

**Module: db/**
Handles all database operations

.. code-block:: text

    modules/db/
    ├── __init__.py
    ├── postgres_connector.py    # PostgreSQL connection management
    ├── mongo_connector.py       # MongoDB operations
    └── query_builder.py         # SQL query construction

Key Classes:
- ``PostgresConnector``: Connection pooling and query execution
- ``MongoConnector``: Document insertion and queries
- ``QueryBuilder``: Parameterized query construction

**Module: input/**
Data ingestion and loading

.. code-block:: text

    modules/input/
    ├── __init__.py
    ├── market_data_loader.py    # yfinance data retrieval
    ├── company_loader.py        # Reference data loading
    └── data_validator.py        # Input validation

Key Classes:
- ``MarketDataLoader``: Fetches OHLCV data for stocks
- ``CompanyLoader``: Loads company universe from PostgreSQL
- ``DataValidator``: Validates input data quality

**Module: processing/**
Core analytics and factor calculations

.. code-block:: text

    modules/processing/
    ├── __init__.py
    ├── risk.py                  # VAR-95, ATR calculations
    ├── momentum.py              # Momentum and returns
    ├── liquidity.py             # Volume and spread metrics
    ├── composite_score.py       # Multi-factor scoring
    ├── sector_analysis.py       # Sector exposure analysis
    └── trend.py                 # Trend identification

Key Classes:
- ``RiskCalculator``: VAR-95, ATR-14 computation
- ``MomentumCalculator``: Returns, momentum metrics
- ``LiquidityCalculator``: Volume and spread analysis
- ``CompositeScorer``: Multi-factor portfolio selection
- ``TrendAnalyzer``: Trend identification

**Module: signals/**
Trading signal generation

.. code-block:: text

    modules/signals/
    ├── __init__.py
    ├── execution_signals.py     # MACD and ATR signals
    ├── signal_strength.py       # Signal confidence metrics
    └── signal_filter.py         # Signal validation

Key Classes:
- ``ExecutionSignalGenerator``: MACD, ATR-based signals
- ``SignalStrengthCalculator``: Confidence and reliability
- ``SignalFilter``: Post-generation filtering

**Module: output/**
Results export and reporting

.. code-block:: text

    modules/output/
    ├── __init__.py
    ├── results_exporter.py      # Multi-format export
    └── analytics_generator.py   # Summary reports

Key Classes:
- ``ResultsExporter``: CSV, Parquet, JSON export
- ``AnalyticsGenerator``: Summary statistics

**Module: storage/**
External storage integration

.. code-block:: text

    modules/storage/
    ├── __init__.py
    ├── minio_storage.py         # MinIO (S3) operations
    └── datalake_writer.py       # Data lake management

Key Classes:
- ``MinIOStorage``: Object upload/download
- ``DataLakeWriter``: Hierarchical data organization

Data Flow Pipeline
------------------

**Stage 1: Data Ingestion**

.. code-block:: python

    # Load company universe from PostgreSQL
    companies = CompanyLoader.load_from_database()  # 678 companies

    # Fetch historical price data
    market_data = MarketDataLoader.fetch_data(
        symbols=companies.symbol,
        start_date='2021-01-01',
        end_date='2026-03-08'
    )

    # Validate data quality
    validated_data = DataValidator.validate(market_data)

**Stage 2: Risk Analysis**

.. code-block:: python

    # Calculate Value-at-Risk (95th percentile)
    var_95 = RiskCalculator.calculate_var_95(
        returns=market_data['returns'],
        window=252,  # 1-year rolling window
        confidence=0.95
    )

    # Calculate Average True Range (14-day)
    atr_14 = RiskCalculator.calculate_atr_pct(
        high=market_data['High'],
        low=market_data['Low'],
        close=market_data['Close'],
        period=14
    )

    # Filter eligible stocks (VAR < 5%, ATR > 1%)
    eligible_stocks = filter_by_risk_metrics(var_95, atr_14)

**Stage 3: Portfolio Selection**

.. code-block:: python

    # Calculate momentum metrics
    momentum = MomentumCalculator.calculate_returns(
        prices=market_data['Close'],
        periods=[1, 5, 20, 60]
    )

    # Calculate liquidity metrics
    liquidity = LiquidityCalculator.calculate_spread(
        high=market_data['High'],
        low=market_data['Low'],
        close=market_data['Close'],
        volume=market_data['Volume']
    )

    # Compute composite score (multi-factor)
    scores = CompositeScorer.calculate_score(
        risk_metrics=var_95,
        momentum=momentum,
        liquidity=liquidity,
        sector=sector_exposure
    )

    # Select top 130 stocks
    selected_stocks = scores.nlargest(130, 'composite_score')

**Stage 4: Signal Generation**

.. code-block:: python

    # Generate MACD signals
    macd_signals = ExecutionSignalGenerator.calculate_macd(
        prices=market_data['Close'],
        fast_period=12,
        slow_period=26,
        signal_period=9
    )

    # Combine with ATR-based confirmation
    final_signals = ExecutionSignalGenerator.combine_signals(
        macd=macd_signals,
        atr=atr_14,
        threshold=0.5
    )

    # Calculate signal strength
    strength = SignalStrengthCalculator.calculate_strength(signals=final_signals)

    # Filter signals
    validated_signals = SignalFilter.filter(
        signals=final_signals,
        min_strength=0.7,
        max_age_days=5
    )

**Stage 5: Export & Storage**

.. code-block:: python

    # Store results in PostgreSQL
    DatabaseExporter.export_selections(
        data=selected_stocks,
        table='portfolio_selections'
    )

    # Export signals to PostgreSQL
    DatabaseExporter.export_signals(
        data=validated_signals,
        table='trading_signals'
    )

    # Upload to MinIO
    MinIOStorage.upload_results(
        results=validated_signals,
        bucket='investment-data',
        path='signals/2026-03-08/'
    )

    # Store documents in MongoDB
    MongoConnector.insert_documents(
        collection='signal_metadata',
        documents=signal_metadata
    )

Key Metrics & Calculations
---------------------------

**Value-at-Risk (VAR-95)**

Calculates the 95th percentile loss:

$$\text{VAR}_{95} = \text{quantile}(\text{returns}, 0.05)$$

Window: 252 days (1 year of trading)

**Average True Range (ATR)**

Normalized volatility measure:

$$\text{ATR\%} = \frac{\text{ATR}_{14}}{\text{Close Price}} \times 100$$

**Composite Score**

Multi-factor normalized score (0-100):

$$\text{Score} = w_1 \times \text{Momentum} + w_2 \times \text{Liquidity} + w_3 \times \text{Trend} - w_4 \times \text{Risk}$$

Default weights: [0.30, 0.25, 0.25, 0.20]

**MACD Signal**

Technical indicator for trend identification:

- MACD = EMA(12) - EMA(26)
- Signal = EMA(MACD, 9)
- Histogram = MACD - Signal

Database Schema
---------------

**PostgreSQL Tables**

.. code-block:: sql

    systematic_equity.company_static
    - symbol (Primary Key)
    - security, gics_sector, gics_industry
    - country, region

    systematic_equity.portfolio_selections
    - symbol, composite_score, ranking
    - momentum, liquidity, trend_score
    - risk_score, selection_date

    systematic_equity.trading_signals
    - id, symbol, signal_type (BUY/SELL)
    - signal_strength, macd_value
    - atr_value, signal_date

Configuration Management
------------------------

Settings are managed through ``config/conf.yaml``:

.. code-block:: yaml

    database:
      host: localhost
      port: 5439
      pool_size: 10
      timeout: 30

    processing:
      var_window: 252
      atr_period: 14
      momentum_periods: [1, 5, 20, 60]
      min_liquidity: 1000000

    output:
      format: parquet
      compression: snappy

Performance Characteristics
----------------------------

**Processing Speed**
- Step 1 (VAR): ~45 seconds for 678 stocks
- Step 2 (Portfolio): ~30 seconds for 597 stocks
- Step 3 (Signals): ~20 seconds for 130 stocks
- Step 4 (Export): ~15 seconds for 335 signals
- **Total**: ~2 minutes end-to-end

**Memory Usage**
- Market data (5 years): ~400 MB
- Intermediate results: ~200 MB
- Peak memory: ~800 MB

**Storage Requirements**
- PostgreSQL data: ~50 MB per month
- MinIO data lake: ~100 MB per month

Scalability Considerations
--------------------------

1. **Universe Expansion**
   - Easily add more stocks to analysis
   - Parallel processing across companies

2. **Additional Factors**
   - Modular processing allows new indicators
   - Add without modifying existing code

3. **Frequency Increase**
   - Intraday analysis possible
   - Incremental updates supported

4. **Multi-Strategy**
   - Create separate signal generators
   - Combine signals into portfolio

Extension Points
----------------

1. **New Risk Metrics**: Add to ``modules/processing/risk.py``
2. **New Signals**: Extend ``modules/signals/execution_signals.py``
3. **New Storage**: Implement ``StorageInterface`` in ``modules/storage/``
4. **New Data Sources**: Add to ``modules/input/``
