Configuration Guide
===================

Overview
--------

The Investment Strategy Data Pipeline uses a YAML-based configuration system. Configuration is defined in ``config/conf.yaml`` and should NOT be committed to version control (added to ``.gitignore``).

Configuration Template
----------------------

Create ``config/conf.yaml`` based on this template:

.. code-block:: yaml

    # ============================================================================
    # Investment Strategy Data Pipeline Configuration
    # ============================================================================
    # IMPORTANT: Add this file to .gitignore - DO NOT commit credentials
    # ============================================================================

    # Database Configuration
    # ============================================================================
    database:
      # PostgreSQL connection details
      host: localhost                 # Database hostname
      port: 5439                      # PostgreSQL port
      user: postgres                  # Database user
      password: postgres              # Database password (use env vars in production)
      database: fift                  # Database name
      schema: systematic_equity       # Default schema

      # Connection pool settings
      pool_size: 10                   # Connection pool size
      timeout: 30                     # Connection timeout (seconds)
      max_overflow: 5                 # Maximum overflow connections

    # MinIO Object Storage Configuration
    # ============================================================================
    minio:
      endpoint: localhost:9000        # MinIO endpoint
      access_key: minioadmin          # Access key (use env vars in production)
      secret_key: minioadmin          # Secret key (use env vars in production)
      bucket: investment-data         # Default bucket
      secure: false                   # Use HTTPS (false for local development)
      region: us-east-1               # S3 region

    # MongoDB Configuration
    # ============================================================================
    mongodb:
      host: localhost                 # MongoDB hostname
      port: 27019                     # MongoDB port
      database: investment_data       # Database name
      username: null                  # Username (optional)
      password: null                  # Password (optional)
      
      collections:
        signals: signal_metadata      # Signal metadata collection
        selections: selection_metadata  # Selection metadata collection

    # Data Processing Configuration
    # ============================================================================
    processing:
      # Risk Metrics
      var_window: 252                 # VAR calculation window (days)
      var_confidence: 0.95            # Confidence level (95th percentile)
      atr_period: 14                  # Average True Range period (days)
      atr_min_pct: 1.0                # Minimum ATR percentage threshold

      # Momentum Metrics
      momentum_periods: [1, 5, 20, 60]  # Return calculation windows (days)
      momentum_min: -100              # Minimum allowed return (%)
      momentum_max: 500               # Maximum allowed return (%)
      momentum_threshold: 0.0         # Momentum filter threshold

      # Liquidity Metrics
      min_daily_volume: 1000000       # Minimum daily volume (USD)
      min_spread_pct: 0.01            # Minimum bid-ask spread (%)
      liquidity_lookback: 20          # Days for liquidity calculation

      # Portfolio Selection
      portfolio_size: 130             # Number of stocks to select
      max_sector_concentration: 0.30  # Max portfolio % per sector
      min_stock_concentration: 0.005  # Min position size (%)

      # Composite Score Weights
      score_weights:
        momentum: 0.30                # Momentum weight
        liquidity: 0.25               # Liquidity weight
        trend: 0.25                   # Trend weight
        risk: 0.20                    # Risk weight (inverted)

    # Signal Generation Configuration
    # ============================================================================
    signals:
      # MACD Parameters
      macd_fast: 12                   # MACD fast EMA period
      macd_slow: 26                   # MACD slow EMA period
      macd_signal: 9                  # Signal line EMA period
      macd_threshold: 0.001           # MACD crossover threshold

      # ATR Confirmation
      atr_multiplier: 2.0             # ATR multiplier for signal strength
      signal_confirmation_periods: 2  # Periods to confirm signal

      # Signal Filters
      min_signal_strength: 0.7        # Minimum signal strength (0-1)
      max_signal_age_days: 5          # Max days before signal expires
      signal_lookback: 10             # Days to look back for signal history

    # Output Configuration
    # ============================================================================
    output:
      # Export Format
      format: parquet                 # Format: parquet or csv
      compression: snappy             # snappy, gzip, or none
      include_intermediate: false     # Export intermediate step results

      # Export Destinations
      export_to_minio: true           # Export to MinIO
      export_to_mongodb: true         # Export to MongoDB
      export_to_csv: true             # Export to CSV files

      # Output Directory
      output_dir: ./results           # Local output directory
      create_subdirs: true            # Create dated subdirectories

    # Logging Configuration
    # ============================================================================
    logging:
      # Log Level: DEBUG, INFO, WARNING, ERROR, CRITICAL
      level: INFO
      
      # Console Output
      console: true                   # Log to console
      console_format: '%(asctime)s %(levelname)s %(name)s: %(message)s'

      # File Output
      file: logs/pipeline.log         # Log file path
      file_format: '%(asctime)s %(levelname)s %(name)s: %(message)s'
      max_bytes: 10485760             # Max log file size (10 MB)
      backup_count: 5                 # Number of backup log files

    # Data Source Configuration
    # ============================================================================
    data:
      # Date Range
      start_date: 2021-01-01          # Historical data start date
      end_date: null                  # End date (null = today)
      
      # Stock Universe
      universe: sp500_russell1000     # Data source universe
      include_international: false    # Include international stocks

      # Data Quality
      min_price: 5.0                  # Minimum stock price (USD)
      min_market_cap: 1000000000      # Minimum market cap (USD 1B)
      exclude_otc: true               # Exclude OTC securities

    # Scheduling Configuration
    # ============================================================================
    scheduling:
      enabled: false                  # Enable scheduled runs
      frequency: monthly              # daily, weekly, monthly, quarterly
      time: '09:30'                   # Execution time HH:MM (24-hour)
      timezone: UTC                   # Timezone for scheduling

      # Run Schedule
      daily_enabled: false
      weekly_enabled: false
      weekly_day: monday              # Day for weekly runs
      monthly_enabled: true
      monthly_day: 1                  # Day of month (1-31)
      quarterly_enabled: false

Environment Variables
---------------------

For production, use environment variables for sensitive credentials:

.. code-block:: bash

    export DB_HOST=your-db-host
    export DB_USER=your-db-user
    export DB_PASSWORD=your-db-password
    export MINIO_ACCESS_KEY=your-access-key
    export MINIO_SECRET_KEY=your-secret-key

Update ``config/conf.yaml``:

.. code-block:: yaml

    database:
      host: ${DB_HOST}
      user: ${DB_USER}
      password: ${DB_PASSWORD}

    minio:
      access_key: ${MINIO_ACCESS_KEY}
      secret_key: ${MINIO_SECRET_KEY}

Common Configuration Scenarios
------------------------------

**Development Environment**

.. code-block:: yaml

    database:
      host: localhost
      port: 5439

    logging:
      level: DEBUG

    processing:
      portfolio_size: 50              # Smaller for testing
      var_window: 100                 # Shorter window

**Production Environment**

.. code-block:: yaml

    database:
      host: prod-db.company.com
      port: 5432
      pool_size: 20
      timeout: 60

    minio:
      secure: true
      endpoint: s3.company.com

    logging:
      level: INFO
      file: /var/log/pipeline/pipeline.log

    processing:
      portfolio_size: 130
      var_window: 252

**High-Frequency Trading**

.. code-block:: yaml

    data:
      end_date: null                  # Use today's data
    
    processing:
      momentum_periods: [1, 5]        # Short-term momentum
      atr_period: 7                   # Shorter volatility window

    signals:
      max_signal_age_days: 1          # Fresh signals only
      min_signal_strength: 0.85       # High confidence only

**Conservative Strategy**

.. code-block:: yaml

    processing:
      portfolio_size: 50              # Fewer positions
      max_sector_concentration: 0.20  # Tighter diversification
      min_signal_strength: 0.9        # Very high confidence

    signals:
      min_signal_strength: 0.9
      signal_confirmation_periods: 5

Configuration Validation
------------------------

Validate your configuration:

.. code-block:: bash

    poetry run python3 << 'EOF'
    import yaml
    from pathlib import Path

    # Load and validate
    with open('config/conf.yaml') as f:
        config = yaml.safe_load(f)

    # Check required keys
    required = ['database', 'processing', 'signals', 'output']
    for key in required:
        assert key in config, f"Missing required section: {key}"

    # Validate values
    assert config['processing']['portfolio_size'] > 0
    assert 0 <= config['processing']['var_confidence'] <= 1

    print("✓ Configuration valid")
    EOF

Accessing Configuration in Code
-------------------------------

Load configuration in Python code:

.. code-block:: python

    import yaml

    # Load configuration
    with open('config/conf.yaml') as f:
        config = yaml.safe_load(f)

    # Access values
    db_host = config['database']['host']
    portfolio_size = config['processing']['portfolio_size']
    signal_strength = config['signals']['min_signal_strength']

Using in modules:

.. code-block:: python

    from modules.config import ConfigLoader

    config = ConfigLoader.load()
    
    # Access nested values
    var_window = config.get('processing.var_window', 252)
    min_volume = config.get('processing.min_daily_volume', 1000000)

Tips & Best Practices
---------------------

1. **Never Commit Credentials**
   
   .. code-block:: bash

       # Ensure in .gitignore
       echo "config/conf.yaml" >> .gitignore

2. **Use Meaningful Names**
   - Choose descriptive database and bucket names
   - Use environment-specific prefixes (dev-, prod-)

3. **Version Your Configuration**
   - Keep a template version without credentials
   - Document changes in CHANGELOG.md

4. **Document Custom Values**
   - Add comments explaining non-obvious settings
   - Include units (days, percentages, USD)

5. **Test Configuration Before Production**
   - Run dry-run with new config
   - Verify all connections work
   - Check output paths are writable

6. **Monitor Configuration Changes**
   - Log config changes
   - Version control templates
   - Alert on unexpected modifications

Troubleshooting Configuration
-----------------------------

**YAML Syntax Errors**

.. code-block:: bash

    # Validate YAML syntax
    poetry run python3 << 'EOF'
    import yaml
    try:
        with open('config/conf.yaml') as f:
            yaml.safe_load(f)
        print("✓ Valid YAML")
    except yaml.YAMLError as e:
        print(f"✗ Error: {e}")
    EOF

**Missing Required Fields**

Ensure all required top-level sections exist:

.. code-block:: yaml

    database: ...
    minio: ...
    processing: ...
    signals: ...
    output: ...
    logging: ...

**Invalid Values**

Check that values are of correct type:

.. code-block:: python

    # Should be integer
    portfolio_size: 130

    # Should be float (0-1)
    var_confidence: 0.95

    # Should be list
    momentum_periods: [1, 5, 20, 60]

    # Should be string
    format: parquet
