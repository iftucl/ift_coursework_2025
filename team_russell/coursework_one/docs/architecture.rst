Architecture Overview
=====================

The system is a **three-pipeline ETL architecture** backed by Kafka,
PostgreSQL, MongoDB, and MinIO.

.. code-block:: text

   PostgreSQL (systematic_equity.company_static — 678-company universe)
           │
           ▼
   [Pipeline A] ◄── Yahoo Finance  (daily prices, 5 years)
                ◄── Yahoo Finance  (annual financials: BS + IS + CF)
                ◄── Alpha Vantage  (alternative financial source, optional)
           │
           ├──────────────────────────────► MinIO (csreport bucket)
           │                                russell/prices/
           │                                russell/balance_sheet/
           │                                russell/income_statement/
           │                                (raw JSON audit trail)
           ▼
      Kafka Topics
      russell.raw_prices
      russell.raw_financials
           │
           ▼
   [Pipeline B] ──► MongoDB        (raw_prices, raw_balance_sheet,
           │                        raw_income_statement collections)
           │
           └──────► PostgreSQL     (systematic_equity.price_history)
                                   (systematic_equity.financials)
                                           │
                                           ▼
                                  [Pipeline C]
                                           │
                                           └──► PostgreSQL
                                                systematic_equity.factor_values

Pipeline A — Data Ingestion
----------------------------

Loads the 678-company universe from ``systematic_equity.company_static``,
then for each company:

1. Fetches daily OHLCV prices from Yahoo Finance and publishes them to the
   ``russell.raw_prices`` Kafka topic and to MinIO
   (``russell/prices/<SYMBOL>_<timestamp>.json``).
2. Fetches annual balance sheet and income statement data and publishes them
   to the ``russell.raw_financials`` Kafka topic and to MinIO.

All raw payloads are serialised as JSON.

Pipeline B — Processing and Storage
-------------------------------------

A long-lived Kafka consumer that:

1. Consumes messages from both Kafka topics.
2. Transforms raw JSON payloads via :mod:`modules.transformer.transformer`.
3. Upserts raw records into MongoDB (audit / replay store).
4. Upserts structured records into PostgreSQL
   (``price_history`` and ``financials`` tables).

Pipeline C — Factor Computation
---------------------------------

A batch job run once per rebalance date (yearly):

1. Loads eligible financial data from PostgreSQL via a multi-CTE SQL query
   with a **3-month look-ahead lag** (filing delay).
2. Applies an eligibility filter: EPS > 0, excludes Financials and Real Estate.
3. Computes 8 raw metrics (4 Value, 4 Quality).
4. Scores each metric using sector-neutral inverse-normal z-scores.
5. Combines into Value and Quality dimension scores (weighted sums,
   weight-renormalised for missing metrics).
6. Computes a composite score (50% Value + 50% Quality), percentile, and
   quintile assignment (Q1 = top 20%, best).
7. Upserts results to ``systematic_equity.factor_values``.

Factor Methodology
------------------

Eligibility Filter
^^^^^^^^^^^^^^^^^^

Applied before scoring at every rebalance:

* **EPS > 0** — loss-making firms excluded.
* **GICS Financials and Real Estate sectors excluded.**

Value Metrics (weight: 50%)
^^^^^^^^^^^^^^^^^^^^^^^^^^^

+--------+-----------------------------------+--------+
| Metric | Formula                           | Weight |
+========+===================================+========+
| B/P    | Book Value / Closing Price        | 15%    |
+--------+-----------------------------------+--------+
| E/Y    | EPS / Closing Price               | 35%    |
+--------+-----------------------------------+--------+
| CF/Y   | Free Cash Flow / Market Cap       | 35%    |
+--------+-----------------------------------+--------+
| DY     | Annual Dividend Rate / Price      | 15%    |
+--------+-----------------------------------+--------+

Quality Metrics (weight: 50%)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

+--------+-----------------------------------+--------+
| Metric | Formula                           | Weight |
+========+===================================+========+
| GPA    | Gross Profit / Total Assets       | 33%    |
+--------+-----------------------------------+--------+
| WCA    | Current Assets / Current Liab.    | 17%    |
+--------+-----------------------------------+--------+
| LTDE   | −(Total Debt / Book Value)        | 33%    |
+--------+-----------------------------------+--------+
| ROA    | Net Income / Total Assets         | 17%    |
+--------+-----------------------------------+--------+

Sector-Neutral Scoring
^^^^^^^^^^^^^^^^^^^^^^

Each metric is scored within GICS sector using three steps:

1. **Winsorise** at 5th / 95th percentile within sector.
2. **Percentile rank** = rank / (N + 1) — strictly between 0 and 1.
3. **Inverse-normal z-score** = Φ⁻¹(percentile) via ``scipy.stats.norm.ppf``.

Sectors with fewer than 5 eligible firms are pooled into a single group.

Database Schema
---------------

``systematic_equity.price_history``
    Daily closing prices and shares outstanding per company.

``systematic_equity.financials``
    Annual balance sheet and income statement fields per company per fiscal year.

``systematic_equity.factor_values``
    Per-company per-year: 8 raw metrics, 8 z-scores, value_score,
    quality_score, composite_score, composite_percentile, quintile, run_id.

Technology Stack
----------------

+---------------------+-----------------------------+-------------------------+
| Component           | Technology                  | Purpose                 |
+=====================+=============================+=========================+
| Message broker      | Apache Kafka (Confluent)    | Decouple A from B       |
+---------------------+-----------------------------+-------------------------+
| Raw store           | MongoDB                     | JSON audit trail        |
+---------------------+-----------------------------+-------------------------+
| Structured store    | PostgreSQL                  | Queryable factor data   |
+---------------------+-----------------------------+-------------------------+
| Object store        | MinIO (S3-compatible)       | Raw file archive        |
+---------------------+-----------------------------+-------------------------+
| Data sources        | Yahoo Finance, Alpha Vantage| Market & financial data |
+---------------------+-----------------------------+-------------------------+
| Package management  | Poetry                      | Dependency management   |
+---------------------+-----------------------------+-------------------------+
| Testing             | pytest + pytest-cov         | 144 tests, ≥88% cov     |
+---------------------+-----------------------------+-------------------------+
| Containerisation    | Docker Compose              | Reproducible infra      |
+---------------------+-----------------------------+-------------------------+
