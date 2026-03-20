Configuration Guide
===================

Overview
--------

The Investment Strategy Data Pipeline uses a YAML-based configuration system. Configuration is defined in ``config/conf.yaml`` and should NOT be committed to version control (added to ``.gitignore``).

Configuration Template
----------------------

Create ``config/conf.yaml`` based on this template. The pipeline reads only the keys shown below — no other sections are required.

.. code-block:: yaml

    # ============================================================================
    # Investment Strategy Data Pipeline Configuration
    # ============================================================================
    # IMPORTANT: Add this file to .gitignore - DO NOT commit credentials
    # ============================================================================

    # PostgreSQL Connection
    # ============================================================================
    postgres:
      host: localhost                 # Database hostname
      port: 5439                      # PostgreSQL port (Docker default)
      user: postgres                  # Database user
      password: postgres              # Database password
      database: fift                  # Database name
      schema: systematic_equity       # Schema for pipeline tables

    # MinIO Object Storage
    # ============================================================================
    minio:
      endpoint: localhost:9000        # MinIO endpoint (host:port, no scheme)
      access_key: ift_bigdata         # Access key
      secret_key: minio_password      # Secret key
      bucket: csreport                # Bucket name (auto-created if missing)
      use_ssl: false                  # Use HTTPS (false for local development)

    # Pipeline Execution Settings
    # ============================================================================
    pipeline:
      run_frequency: daily            # daily, weekly, monthly, quarterly
      historical_years: 5             # Years of price history to fetch

Key Configuration Notes
-----------------------

**Composite Scoring Weights (hardcoded in pipeline)**

The composite score formula is fixed at:

.. code-block:: text

    score = 0.6 \u00b7 Z(momentum) + 0.2 \u00b7 Z(liquidity) - 0.2 \u00b7 Z(risk)

Where all z-scores are computed **within each sector** (sector-relative normalisation).
Weights are not read from conf.yaml; they are defined directly in
``pipeline/calculate_composite_portfolio.py``.

**Portfolio Size**

Portfolio size is **not** a fixed number. The pipeline selects the top 20% of stocks
within each sector, so the final count depends on the universe size and sector distribution
for the run date.

**MinIO Credential Resolution**

Credentials are resolved in this order (first match wins):

1. Environment variables: ``MINIO_ENDPOINT``, ``MINIO_ACCESS_KEY``, ``MINIO_SECRET_KEY``, ``MINIO_BUCKET``
2. ``config/conf.yaml`` ``minio:`` section (fallback for local development)

Environment Variables
---------------------

Override ``conf.yaml`` at runtime for CI/CD or production deployments:

.. code-block:: bash

    export MINIO_ENDPOINT=your-minio-host:9000
    export MINIO_ACCESS_KEY=your-access-key
    export MINIO_SECRET_KEY=your-secret-key
    export MINIO_BUCKET=your-bucket

    # Optional: fail the pipeline if MinIO upload fails
    export MINIO_REQUIRED=true

Common Configuration Scenarios
------------------------------

**Local Development (Docker)**

Below is the full ``config/conf.yaml`` for a local Docker-based setup:

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

**Production (Remote Services)**

.. code-block:: yaml

    postgres:
      host: prod-db.company.com
      port: 5432
      user: pipeline_user
      password: secure_password
      database: fift
      schema: systematic_equity

    minio:
      endpoint: s3.company.com:443
      access_key: prod_access_key
      secret_key: prod_secret_key
      bucket: pipeline-data
      use_ssl: true

    pipeline:
      run_frequency: monthly
      historical_years: 5

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
    - Document changes in the team-level ``../CHANGELOG.md``

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
