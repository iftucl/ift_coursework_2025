Troubleshooting Guide
=====================

Common Issues
-------------

**Pipeline Won't Start**

Error Message: ``ModuleNotFoundError: No module named 'modules'``

Solution:

.. code-block:: bash

    # Verify Python path
    cd /path/to/coursework_one
    
    # Reinstall dependencies
    poetry install --no-cache
    
    # Verify installation
    poetry run python3 -c "import modules; print('OK')"

**Database Connection Failed**

Error Message: ``psycopg2.OperationalError: could not connect to server``

Solution:

.. code-block:: bash

    # 1. Check PostgreSQL is running
    docker compose ps postgres_db
    
    # 2. Verify credentials in config/conf.yaml
    cat config/conf.yaml | grep -A 5 database:
    
    # 3. Test connection manually
    psql -h localhost -p 5439 -U postgres -d fift
    
    # 4. Restart service if needed
    docker compose restart postgres_db

**Missing Data for Specific Date**

Error Message: ``No data returned for symbol AAPL on 2026-03-08``

Solution:

.. code-block:: bash

    # Check yfinance has data
    poetry run python3 << 'EOF'
    import yfinance as yf
    data = yf.download('AAPL', start='2026-01-01', end='2026-03-08')
    print(f"Records: {len(data)}")
    print(f"Date range: {data.index[0]} to {data.index[-1]}")
    EOF
    
    # Use a date with market data
    poetry run python3 main.py --run-date 2026-03-06

**Out of Memory**

Error Message: ``MemoryError`` or system swap usage increasing

Solution:

.. code-block:: bash

    # Check available memory
    free -h  # Linux
    vm_stat  # macOS
    
    # Reduce portfolio size
    # Edit config/conf.yaml:
    # processing:
    #   portfolio_size: 50  # reduced from 130
    
    # Or increase system memory
    # Docker: Increase memory allocation
    # Kubernetes: Request more resources

**Slow Pipeline Execution**

Pipeline takes > 5 minutes instead of ~2 minutes

Solution:

.. code-block:: bash

    # 1. Check PostgreSQL performance
    docker compose logs postgres_db | grep slow
    
    # 2. Check network connectivity
    ping -c 5 localhost
    
    # 3. Increase connection pool
    # Edit config/conf.yaml:
    # database:
    #   pool_size: 20  # increased from 10
    
    # 4. Disable unnecessary exports
    # Edit config/conf.yaml:
    # output:
    #   export_to_minio: false

**Invalid Configuration**

Error Message: ``ConfigError: Invalid value for processing.var_window``

Solution:

.. code-block:: bash

    # Validate configuration
    poetry run python3 << 'EOF'
    import yaml
    import sys
    
    with open('config/conf.yaml') as f:
        config = yaml.safe_load(f)
    
    # Check types
    assert isinstance(config['processing']['var_window'], int), "var_window must be integer"
    assert config['processing']['var_window'] > 0, "var_window must be positive"
    
    print("✓ Config valid")
    EOF

**Test Failures**

Error Message: ``FAILED test/test_risk.py::TestRisk::test_var_calculation``

Solution:

.. code-block:: bash

    # Run with verbose output
    poetry run pytest test/test_risk.py -vv
    
    # Check specific test
    poetry run pytest test/test_risk.py::TestRisk::test_var_calculation -s
    
    # View test logs
    tail -50 logs/test.log

Performance Issues
------------------

**Slow Stock Universe Loading**

Symptom: Step 1 takes > 60 seconds for 678 stocks

.. code-block:: python

    # Use parallel processing
    from multiprocessing import Pool
    
    # In market_data_loader.py:
    with Pool(processes=4) as pool:
        results = pool.map(fetch_stock_data, symbols)

**Database Queries Are Slow**

Symptom: Inserting results takes > 30 seconds

Solution:

.. code-block:: sql

    -- Add indexes to PostgreSQL
    CREATE INDEX idx_company_symbol ON systematic_equity.company_static(symbol);
    CREATE INDEX idx_signals_date ON systematic_equity.trading_signals(signal_date);
    CREATE INDEX idx_selections_date ON systematic_equity.portfolio_selections(selection_date);

**MinIO Upload Fails**

Symptom: ``MinIOError: Unable to connect to endpoint``

Solution:

.. code-block:: bash

    # Check MinIO is running
    docker compose ps minio
    
    # Verify MinIO connectivity
    mc alias set minio http://localhost:9000 minioadmin minioadmin
    mc ls minio/investment-data/
    
    # Restart MinIO
    docker compose restart minio

Data Quality Issues
-------------------

**Missing VAR Calculation for Some Stocks**

Symptom: Only 590/678 stocks have VAR calculated

Common causes:
- Insufficient historical data (< 252 days)
- Too few trading days
- Delisted stocks

Solution:

.. code-block:: python

    # Check data availability
    stocks_with_data = data[data['Close'].notna()]
    print(f"Stocks with sufficient data: {len(stocks_with_data)}")
    
    # Filter stocks
    eligible = data[
        (data['Close'].notna()) & 
        (data.groupby('symbol').size() >= 252)
    ]

**High Number of NULL Values in Output**

Symptom: Portfolio selections have missing composite scores

Solution:

.. code-block:: python

    # Validate required columns before scoring
    required = ['symbol', 'risk_adjusted_momentum_252', 'volume_60d_avg', 'var_95']
    missing = [c for c in required if c not in data.columns]

    if missing:
        print(f"Missing columns: {missing}")
    else:
        print("Input schema looks valid")

**Duplicate Records in Database**

Symptom: Same signal appears multiple times

Solution:

.. code-block:: bash

    # Check for duplicates
    docker compose exec postgres_db psql -U postgres -d fift << 'SQL'
    SELECT symbol, signal_date, COUNT(*) 
    FROM systematic_equity.trading_signals 
    GROUP BY symbol, signal_date 
    HAVING COUNT(*) > 1;
    SQL
    
    # Clean duplicates
    DELETE FROM systematic_equity.trading_signals a
    WHERE a.ctid > (
        SELECT min(b.ctid) 
        FROM systematic_equity.trading_signals b
        WHERE b.symbol = a.symbol AND b.signal_date = a.signal_date
    );

Integration Issues
------------------

**MinIO Bucket Not Found**

Error Message: ``NoSuchBucket: The specified bucket does not exist.``

Solution:

.. code-block:: bash

    # Create bucket
    mc mb minio/investment-data
    
    # Verify
    mc ls minio/

**MongoDB Connection Timeout**

Error Message: ``ConnectionFailure: ...``

Solution:

.. code-block:: bash

    # Check MongoDB is running
    docker compose ps mongo_db
    
    # Test connection
    poetry run python3 << 'EOF'
    from pymongo import MongoClient
    client = MongoClient('localhost', 27019)
    print("✓ Connected to MongoDB")
    EOF

**PostgreSQL Schema Issues**

Error Message: ``relation ... does not exist``

Solution:

.. code-block:: bash

    # Recreate schema
    docker compose exec postgres_db psql -U postgres -d fift -f /create_tables.sql
    
    # Verify tables
    docker compose exec postgres_db psql -U postgres -d fift << 'SQL'
    SELECT table_name FROM information_schema.tables 
    WHERE table_schema = 'systematic_equity';
    SQL

Logging & Debugging
-------------------

**Enable Debug Logging**

.. code-block:: bash

    # Set log level
    export LOGLEVEL=DEBUG
    poetry run python3 main.py --dry-run
    
    # Or in config/conf.yaml:
    # logging:
    #   level: DEBUG

**View Detailed Logs**

.. code-block:: bash

    # Real-time log monitoring
    tail -f logs/pipeline.log
    
    # Search for errors
    grep ERROR logs/pipeline.log
    
    # View last 100 lines
    tail -100 logs/pipeline.log

**Export Debug Information**

.. code-block:: python

    import logging
    
    # Enable debug output
    logging.basicConfig(level=logging.DEBUG)
    
    # Add custom debug info
    logger = logging.getLogger(__name__)
    logger.debug(f"Processing {len(stocks)} stocks")

Getting Help
------------

1. **Check the FAQ**: :doc:`FAQ <faq>`
2. **Review Logs**: ``logs/pipeline.log``
3. **Run Tests**: ``poetry run pytest -v``
4. **Validate Configuration**: Run config validation scripts
5. **Contact Support**: Check GitHub issues or project documentation
