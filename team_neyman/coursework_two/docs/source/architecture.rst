Architecture Overview
=====================

The system is a **Multi-Tiered Quantitative Investment Pipeline**. It is built on the principle of **Polyglot Persistence**—using different database technologies for the specific types of data they handle best.

System Components
-----------------

1. **Data Storage Layer (The Triple-Threat)**:

   Unlike a standard app, you are using three distinct storage engines:

   * **Relational (PostgreSQL):** This is your "Source of Truth" for structured market data. It handles the OHLCV (Open, High, Low, Close, Volume) and FX (Foreign Exchange) data. It uses UPSERT logic to ensure no duplicate price dates exist.
   * **Document-Oriented (MongoDB):** This handles the "messy" data. It stores trade logs, pending orders, and portfolio metadata. Since trades can have varying numbers of assets, the schema-less nature of Mongo is used here.
   * **Object Storage (MinIO):** This acts as your **Analytical Data Lake**. You aren't storing daily holdings in a database; you are serializing them into **Apache Parquet** files. This allows for high-speed columnar reads when running return analysis.

2. **The Factor Engine (Transformation)**:

   Located in ``modules/factors/``, this layer extracts raw prices from Postgres and transforms them into actionable signals:

   * **Vectorized Calculations:** Using ``pandas`` and ``numpy`` to calculate technical indicators (Momentum, Moving Averages, ADX).
   * **Data Validation:** It filters for null rates to ensure a "garbage in, garbage out" scenario doesn't happen.
   
3. **Investment & Execution Logic**:

   This is the "Brain" of the system (``modules/investment/``):

   * **Backtesting Engine:** A discrete-time simulator that iterates through historical business days.
   * **Rebalancing Logic:** Every month (or specified period), the system calculates new target weights and generates "Pending" trades in MongoDB.
   * **MTM (Mark-to-Market) Update:** Your update_holdings logic recalculates the value of the portfolio daily, handling the tricky **GBp (Pence)** vs. **GBP (Pounds)** conversion for London-listed stocks.

4. **Analysis & Reporting**:

   The ``modules/analysis/`` layer reads the Parquet snapshots from MinIO to generate:

   * **Equity Curves:**: Visualizing performance against a benchmark.
   * **Risk Metrics:**: Volatility and Sector exposure.
