API Reference
==============

Core Modules
------------

The Investment Strategy Data Pipeline is organized into modular components:

.. toctree::
   :maxdepth: 2

   database
   input
   processing
   signals
   output
   storage

Module Overview
---------------

**Database Module (modules/db/)**

Database connectivity and operations

.. autosummary::
   :nosignatures:

   modules.db.postgres_connector.PostgresConnector

**Input Module (modules/input/)**

Data loading and ingestion

.. autosummary::
   :nosignatures:

   modules.input.market_data_loader.MarketDataLoader
   modules.input.company_loader.CompanyLoader
   modules.input.data_validator.DataValidator

**Processing Module (modules/processing/)**

Factor calculations and analysis

.. autosummary::
   :nosignatures:

   modules.processing.risk.RiskCalculator
   modules.processing.momentum.MomentumCalculator
   modules.processing.liquidity.LiquidityCalculator
   modules.processing.composite_score.CompositeScorer
   modules.processing.trend.TrendAnalyzer

**Signals Module (modules/signals/)**

Trading signal generation

.. autosummary::
   :nosignatures:

   modules.signals.execution_signals.ExecutionSignalGenerator
   modules.signals.signal_strength.SignalStrengthCalculator
   modules.signals.signal_filter.SignalFilter

**Output Module (modules/output/)**

Results export and reporting

.. autosummary::
   :nosignatures:

   modules.output.results_exporter.ResultsExporter
   modules.output.analytics_generator.AnalyticsGenerator

**Storage Module (modules/storage/)**

External storage integration

.. autosummary::
   :nosignatures:

   modules.storage.minio_storage.MinIOStorage
   modules.storage.datalake_writer.DataLakeWriter

Quick Reference
---------------

**Loading Market Data**

.. code-block:: python

    from modules.input.market_data_loader import MarketDataLoader

    loader = MarketDataLoader()
    data = loader.fetch_data(
        symbols=['AAPL', 'MSFT'],
        start_date='2021-01-01',
        end_date='2026-03-08'
    )

**Calculating Risk Metrics**

.. code-block:: python

    from modules.processing.risk import RiskCalculator

    var_95 = RiskCalculator.calculate_var_95(
        returns=data['returns'],
        window=252,
        confidence=0.95
    )

    atr = RiskCalculator.calculate_atr_pct(
        high=data['High'],
        low=data['Low'],
        close=data['Close'],
        period=14
    )

**Generating Signals**

.. code-block:: python

    from modules.signals.execution_signals import ExecutionSignalGenerator

    generator = ExecutionSignalGenerator()
    signals = generator.calculate_macd(
        prices=data['Close'],
        fast_period=12,
        slow_period=26,
        signal_period=9
    )

**Exporting Results**

.. code-block:: python

    from modules.output.results_exporter import ResultsExporter

    exporter = ResultsExporter()
    exporter.export_to_csv(
        dataframe=results,
        filename='results.csv'
    )

**Storing in MinIO**

.. code-block:: python

    from modules.storage.minio_storage import MinIOStorage

    storage = MinIOStorage(
        endpoint='localhost:9000',
        access_key='minioadmin',
        secret_key='minioadmin'
    )
    
    storage.upload_file(
        bucket='investment-data',
        object_name='signals/2026-03-08.parquet',
        file_path='local_results.parquet'
    )

Error Handling
--------------

All modules include proper error handling:

.. code-block:: python

    from modules.input.market_data_loader import MarketDataLoader
    from modules.exceptions import DataLoadError

    try:
        data = MarketDataLoader.fetch_data(symbols=['INVALID'])
    except DataLoadError as e:
        print(f"Failed to load data: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

Common Exceptions
~~~~~~~~~~~~~~~~~

- ``DataLoadError``: Failed to load market data
- ``DatabaseError``: Database connection or query error
- ``ValidationError``: Data validation failure
- ``ConfigError``: Configuration parsing error
- ``StorageError``: MinIO or file storage error

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
