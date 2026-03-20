Usage Instructions
==================

Running the Pipeline
--------------------

**Primary Entry Point**

The main entry point for running the pipeline is ``main.py``:

.. code-block:: bash

    poetry run python3 main.py [OPTIONS]

**Available Options**

.. code-block:: bash

    Options:
      --frequency {daily|weekly|monthly|quarterly}
                    Pipeline execution frequency (default: monthly)
      --run-date DATE
                    Specific date for analysis (YYYY-MM-DD format)
      --dry-run     Execute without database writes
      --help        Show help message

**Frequency Options**

- ``daily``: Run once per day (early morning recommended)
- ``weekly``: Run on Monday mornings
- ``monthly``: Run on first business day of month
- ``quarterly``: Run on first business day of quarter

Common Usage Scenarios
---------------------

**1. Daily Trading Strategy**

.. code-block:: bash

    # Run daily analysis
    poetry run python3 main.py --frequency daily

    # Schedule with cron (add to crontab)
    # 09:30 * * * * cd /path/to/coursework_one && poetry run python3 main.py --frequency daily

**2. Weekly Portfolio Review**

.. code-block:: bash

    # Run weekly updates
    poetry run python3 main.py --frequency weekly

**3. Monthly Reporting**

.. code-block:: bash

    # Run monthly analysis
    poetry run python3 main.py --frequency monthly

**4. Historical Analysis**

.. code-block:: bash

    # Analyze specific date
    poetry run python3 main.py --run-date 2026-02-15

    # Backtest multiple dates
    for date in 2026-01-15 2026-02-15 2026-03-15; do
        poetry run python3 main.py --run-date $date
    done

**5. Testing (Dry Run)**

.. code-block:: bash

    # Test without database changes
    poetry run python3 main.py --dry-run

    # Test specific configuration
    poetry run python3 main.py --dry-run --frequency monthly

Accessing Results
-----------------

**PostgreSQL Database**

Connect to view results:

.. code-block:: bash

    psql -h localhost -p 5439 -U postgres -d fift

Query selections:

.. code-block:: sql

    SELECT symbol, composite_score, ranking
    FROM systematic_equity.portfolio_selections
    WHERE selection_date = CURRENT_DATE
    ORDER BY ranking ASC
    LIMIT 10;

Query signals:

.. code-block:: sql

    SELECT symbol, signal_type, signal_strength, macd_value
    FROM systematic_equity.trading_signals
    WHERE signal_date = CURRENT_DATE
    AND signal_type = 'BUY'
    ORDER BY signal_strength DESC;

**MinIO (Data Lake)**

Access exported analytics:

.. code-block:: bash

    # List available data
    mc ls minio/csreport/

    # Download results
    mc cp minio/csreport/processed/step3/ ./local_results/

**File-Based Results**

Pipeline exports to structured directories under ``analytics/``:

.. code-block:: bash

    # Step 1: factor data (all stocks)
    ls analytics/processed/step1/

    # Step 2: portfolio selections
    ls analytics/processed/step2/
    ls analytics/serving/selections/

    # Step 3: trading signals
    ls analytics/processed/step3/
    ls analytics/serving/signals/

Monitoring Pipeline Execution
------------------------------

**View Logs**

.. code-block:: bash

    # Real-time log monitoring (pipeline.log is in the project root)
    tail -f pipeline.log

    # Search for errors
    grep ERROR pipeline.log

    # View last execution
    tail -100 pipeline.log | grep "Step"

**Performance Metrics**

Monitor execution time by step:

.. code-block:: bash

    grep "Step.*completed" logs/pipeline.log | tail -4

Expected output:

.. code-block:: text

    2026-03-08 10:15:23 INFO Step 1: VAR calculation completed (45s)
    2026-03-08 10:16:08 INFO Step 2: Portfolio selection completed (30s)
    2026-03-08 10:16:38 INFO Step 3: Signal generation completed (20s)
    2026-03-08 10:16:53 INFO Step 4: Export completed (15s)

Configuration
-------------

**Main Configuration File**

Create ``config/conf.yaml``:

.. code-block:: yaml

    # Database Configuration
    database:
      host: localhost
      port: 5439
      user: postgres
      password: postgres
      database: fift
      schema: systematic_equity
      pool_size: 10
      timeout: 30

    # MinIO Configuration
    minio:
      endpoint: localhost:9000
      access_key: minioadmin
      secret_key: minioadmin
      bucket: investment-data
      secure: false

    # MongoDB Configuration
    mongodb:
      host: localhost
      port: 27019
      database: investment_data
      collection: signals

    # Data Processing Parameters
    processing:
      # Risk metrics
      var_window: 252              # 1-year rolling window
      var_confidence: 0.95         # 95th percentile
      atr_period: 14               # Average True Range period
      atr_min_pct: 1.0             # Minimum ATR %

      # Momentum metrics
      momentum_periods: [1, 5, 20, 60]  # Return windows
      momentum_min: -100           # Minimum return threshold
      momentum_max: 500            # Maximum return threshold

      # Liquidity metrics
      min_daily_volume: 1000000    # Minimum daily volume (USD)
      min_spread_pct: 0.01         # Minimum bid-ask spread

      # Portfolio selection
      portfolio_size: 130          # Number of stocks to select
      max_sector_concentration: 0.30  # Max % per sector

    # Signal Generation Parameters
    signals:
      # MACD parameters
      macd_fast: 12
      macd_slow: 26
      macd_signal: 9
      macd_threshold: 0.001

      # ATR confirmation
      atr_multiplier: 2.0
      signal_confirmation_periods: 2

      # Signal filters
      min_signal_strength: 0.7
      max_signal_age_days: 5

    # Output Configuration
    output:
      format: parquet              # parquet or csv
      compression: snappy
      include_intermediate: false
      export_to_minio: true
      export_to_mongodb: true

    # Logging
    logging:
      level: INFO                  # DEBUG, INFO, WARNING, ERROR
      file: logs/pipeline.log
      console: true
      max_bytes: 10485760          # 10 MB
      backup_count: 5

**Custom Parameters**

Modify processing parameters:

.. code-block:: yaml

    processing:
      var_window: 504              # 2-year rolling window
      portfolio_size: 200          # Increase selection size
      max_sector_concentration: 0.25  # Stricter sector limits

Troubleshooting Usage
---------------------

**Pipeline Won't Start**

.. code-block:: bash

    # Check configuration file exists
    test -f config/conf.yaml && echo "Config OK" || echo "Missing config/conf.yaml"

    # Validate YAML syntax
    poetry run python3 << 'EOF'
    import yaml
    with open('config/conf.yaml') as f:
        config = yaml.safe_load(f)
    print("✓ Config valid")
    EOF

**Database Connection Issues**

.. code-block:: bash

    # Test PostgreSQL connection
    poetry run python3 << 'EOF'
    import psycopg2
    from yaml import safe_load
    
    with open('config/conf.yaml') as f:
        config = safe_load(f)
    
    conn = psycopg2.connect(**config['database'])
    print(f"✓ Connected to {config['database']['database']}")
    conn.close()
    EOF

**Slow Pipeline Execution**

1. **Increase memory allocation**
   - Default: 8GB, Recommended: 16GB
   - Check: ``free -h`` (Linux) or ``top`` (macOS)

2. **Enable connection pooling**
   - Edit ``config/conf.yaml``
   - Increase ``database.pool_size`` to 20

3. **Reduce portfolio size for testing**
   - Edit ``config/conf.yaml``
   - Set ``processing.portfolio_size: 50`` temporarily

**Missing Market Data**

.. code-block:: bash

    # Check data availability
    poetry run python3 << 'EOF'
    from modules.input.market_data_loader import MarketDataLoader
    
    data = MarketDataLoader.fetch_data(
        symbols=['AAPL'],
        start_date='2021-01-01',
        end_date='2026-03-08'
    )
    print(f"✓ Data shape: {data.shape}")
    print(f"✓ Date range: {data.index[0]} to {data.index[-1]}")
    EOF

Advanced Usage
--------------

**Running Specific Steps**

Import and run individual steps:

.. code-block:: python

    from modules.processing.risk import RiskCalculator
    from modules.input.market_data_loader import MarketDataLoader

    # Load data
    data = MarketDataLoader.fetch_data(['AAPL'], '2021-01-01', '2026-03-08')

    # Calculate VAR
    var_95 = RiskCalculator.calculate_var_95(data, window=252)
    print(f"VAR-95: {var_95:.4f}")

**Custom Analysis**

Create custom analysis scripts:

.. code-block:: python

    import sys
    sys.path.insert(0, '.')
    
    from modules.input.company_loader import CompanyLoader
    from modules.processing.composite_score import CompositeScorer
    
    # Load companies
    companies = CompanyLoader.load_from_database()
    
    # Calculate scores
    scorer = CompositeScorer()
    scores = scorer.calculate_score(
        risk_metrics=risk_data,
        momentum=momentum_data,
        liquidity=liquidity_data
    )
    
    # Export results
    scores.to_csv('custom_analysis.csv', index=False)

**Scheduling Automated Runs**

Using cron on Unix/Linux:

.. code-block:: bash

    # Edit crontab
    crontab -e

    # Add daily run at 9:30 AM
    30 9 * * * cd /path/to/coursework_one && poetry run python3 main.py --frequency daily >> /tmp/pipeline.log 2>&1

    # Add weekly run at 8:00 AM Monday
    0 8 * * 1 cd /path/to/coursework_one && poetry run python3 main.py --frequency weekly >> /tmp/pipeline.log 2>&1

Using systemd timer (more robust):

.. code-block:: ini

    # /etc/systemd/system/pipeline.service
    [Unit]
    Description=Investment Strategy Data Pipeline
    After=network.target

    [Service]
    Type=oneshot
    WorkingDirectory=/path/to/coursework_one
    ExecStart=/usr/bin/poetry run python3 main.py --frequency daily
    User=investor

    # /etc/systemd/system/pipeline.timer
    [Unit]
    Description=Run pipeline daily at 9:30 AM
    Requires=pipeline.service

    [Timer]
    OnCalendar=*-*-* 09:30:00
    Persistent=true

    [Install]
    WantedBy=timers.target

Next Steps
----------

- :doc:`Review Architecture <architecture>` for technical details
- :doc:`Check API Reference <api/index>` for specific functions
- :doc:`Troubleshooting <troubleshooting>` for common issues
- :doc:`FAQ <faq>` for frequently asked questions
