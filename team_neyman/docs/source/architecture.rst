Architecture Overview
=====================

The system implements a modular **ETL (Extract, Transform, Load)** pipeline designed for quantitative financial analysis. It prioritizes data integrity, environment parity, and analytical scalability.

System Components
-----------------

1. **Relational Layer (PostgreSQL)**

   * **Role**: Primary data store for structured market data.
   * **Mechanism**: Handles high-frequency row-level updates and "UPSERT" logic for OHLCV data.
   * **Persistence**: Ensures that factor results (ADX, Momentum, MA) are immediately queryable via SQL.

2. **Analytical Layer (MinIO & Parquet)**

   * **Role**: High-performance "Data Lake" storage.
   * **Mechanism**: Persists final daily reports in **Apache Parquet** format.
   * **Benefit**: Leverages columnar storage to reduce disk I/O and provides an immutable audit trail of factor signals outside the live database.

3. **Transformation Engine (Pandas & PyArrow)**

   * **Logic**: Implemented in ``calculate_factors.py`` using vectorized operations.
   * **Robustness**: Utilizes defensive shape-alignment to maintain data consistency across varied input shapes.

4. **Orchestration & Execution Layer**

   * **Entry Point**: The ``Main.py`` script coordinates data flow from DoltHub to the database and final object storage.
   * **Infrastructure**: Fully containerized via **Docker Compose**, ensuring a consistent execution environment across all development stages.

Data Flow Path
--------------

1. **Extraction**: Raw data is synchronized from DoltHub repositories.
2. **Transformation**: Technical indicators are calculated and validated for null-rate thresholds.
3. **Relational Load**: Results are indexed and stored in PostgreSQL for immediate access.
4. **Analytical Archive**: Final snapshots are serialized to Parquet and uploaded to the MinIO cluster.