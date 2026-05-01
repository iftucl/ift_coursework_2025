# Team Russell - Coursework One

## Overview

This project implements an **8-metric Value + Quality composite factor data pipeline** for the UCL IFT Big Data in Quantitative Finance coursework.

The pipeline ingests market and financial data for the 678-company investable universe, computes sector-neutral composite factor scores using an inverse-normal z-score methodology, and stores them for use in Coursework Two portfolio construction.

**Composite Score = 50% Value Z-Score + 50% Quality Z-Score**

## Architecture

```
PostgreSQL (systematic_equity.company_static — 678-company investable universe)
        │
        ▼
[Pipeline A] ◄── Yahoo Finance  (daily prices, 5 years)
             ◄── Yahoo Finance  (annual financials: BS + IS + CF, up to 4 years)
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
                                             (8 raw metrics, 8 z-scores,
                                              value_score, quality_score,
                                              composite_score, quintile)
                                             per eligible company per year
```

## Factor Methodology

### Eligibility Filter

Applied before scoring at each rebalance date:
- **EPS > 0** — loss-making firms excluded
- **GICS Financials and Real Estate sectors excluded**

### Investment Universe

- 678 companies from the coursework dataset
- Static universe — no dynamic re-selection
- Eligibility filter applied yearly; ~430 companies pass per rebalance

### Data Inputs

| Data | Source | Frequency |
|---|---|---|
| Closing price, shares outstanding | Yahoo Finance | Daily |
| Total assets, total liabilities | Yahoo Finance | Annual |
| Net income, EBITDA, revenue | Yahoo Finance | Annual |
| Total debt, cash & equivalents | Yahoo Finance | Annual |
| Gross profit, free cash flow | Yahoo Finance | Annual |
| Current assets, current liabilities | Yahoo Finance | Annual |
| Annual dividend rate | Yahoo Finance | Annual |

### Derived Variables

| Variable | Formula |
|---|---|
| Market Cap | Price × Shares Outstanding |
| Book Value | Total Assets − Total Liabilities |
| EPS | Net Income / Shares Outstanding |

### Sector-Neutral Scoring

Each metric is scored **within GICS sector** using a 3-step transformation:

1. **Winsorise** at 5th / 95th percentile within sector
2. **Percentile rank** = rank / (N + 1), giving values strictly between 0 and 1
3. **Inverse-normal z-score** = Φ⁻¹(percentile) via `scipy.stats.norm.ppf`

Sectors with fewer than 5 eligible firms are pooled into a single group.

### Value Component (weight: 50%)

| Metric | Formula | Weight |
|---|---|---|
| B/P | Book Value / Closing Price | 15% |
| E/Y | EPS / Closing Price | 35% |
| CF/Y | Free Cash Flow / Market Cap | 35% |
| DY | Annual Dividend Rate / Price | 15% |

**Value Score** = weighted sum of per-metric z-scores (weights renormalised for missing metrics) → re-ranked across full universe → dimension z-score.

### Quality Component (weight: 50%)

| Metric | Formula | Weight |
|---|---|---|
| GPA | Gross Profit / Total Assets | 33% |
| WCA | Current Assets / Current Liabilities | 17% |
| LTDE | −(Total Debt / Book Value) | 33% |
| ROA | Net Income / Total Assets | 17% |

**Quality Score** = weighted sum of per-metric z-scores → re-ranked across full universe → dimension z-score.

### Composite Score

```
Composite Raw = 0.5 × Value_Z + 0.5 × Quality_Z
             (renormalised to full weight if one dimension missing)
Composite Score = re-rank across universe → composite z-score
Composite Percentile = rank / N  (0 to 1)
Quintile: Q1 = top 20% (best), Q5 = bottom 20% (worst)
```

### Rebalancing

- Frequency: **yearly**
- Rebalance date: **December 31 of each calendar year**
- Financial data lagged 3 months to prevent look-ahead bias (US SEC 10-K filing window)

## Prerequisites

- Docker + Docker Compose
- Python 3.10+
- Poetry (recommended) or pip
- Alpha Vantage API key (free tier — optional, Yahoo Finance used by default)

## Setup

### 1. Start infrastructure

```bash
# From repo root — starts PostgreSQL, MongoDB, MinIO
docker compose up --build postgres_db postgres_seed mongo_db miniocw minio_client_cw pgadmin

# Start Kafka (Team Russell overlay)
docker compose -f docker-compose.yml -f team_russell/coursework_one/docker-compose.kafka.yml up --build zookeeper_russell kafka_russell
```

### 2. Apply Russell schema to PostgreSQL

Run via Docker exec (no local psql required):

```bash
docker exec -i postgres_db_cw psql -U postgres -d fift \
  -f /dev/stdin < team_russell/coursework_one/static/create_russell_tables.sql
```

Or via PgAdmin at http://localhost:5051 (admin@admin.com / root).

### 3. Install Python dependencies

```bash
cd team_russell/coursework_one
poetry install
```

Or with pip:

```bash
pip install psycopg2-binary sqlalchemy "pymongo>=4.6" yfinance requests \
  "confluent-kafka>=2.4" minio pyyaml "pydantic>=2.0" "pandas>=2.2" \
  "numpy>=2.0" "scipy>=1.11" click
pip install pytest pytest-cov
```

### 4. Configure API keys

Copy `a_pipeline/config/conf.example.yaml` to `a_pipeline/config/conf.yaml` and fill in your Alpha Vantage key (only needed if using `--financial-source alphavantage`).

## Running the Pipelines

All commands are run from `team_russell/coursework_one/`.

### Pipeline A — Ingest data

```bash
# Fetch everything (prices + financials) for all 678 companies
poetry run python a_pipeline/main.py --mode all --lookback-years 5

# Prices only
poetry run python a_pipeline/main.py --mode prices

# Financials only (Yahoo Finance, default)
poetry run python a_pipeline/main.py --mode financials
```

### Pipeline B — Process and store (run alongside Pipeline A)

```bash
poetry run python b_pipeline/main.py
# Stop with Ctrl+C once Pipeline A finishes
```

### Pipeline C — Compute composite factor (run yearly)

```bash
poetry run python c_pipeline/main.py --run-date 2022-12-31
poetry run python c_pipeline/main.py --run-date 2023-12-31
poetry run python c_pipeline/main.py --run-date 2024-12-31
poetry run python c_pipeline/main.py --run-date 2025-12-31
```

## Testing

Run tests per pipeline (each pipeline has its own module namespace):

```bash
cd a_pipeline && python -m pytest test/ -v   # 39 tests
cd b_pipeline && python -m pytest test/ -v   # 37 tests
cd c_pipeline && python -m pytest test/ -v   # 68 tests
```

Total: **144 tests, 0 failures**.

## Output Schema

`systematic_equity.factor_values`:

| Column | Description |
|---|---|
| symbol | Company ticker |
| period_date | Year-end rebalance date |
| run_id | Pipeline run identifier (timestamp) |
| market_cap | Price × Shares Outstanding |
| book_value | Total Assets − Total Liabilities |
| bp | Book-to-Price (B/P) |
| ey | Earnings Yield (E/Y) |
| cfy | Cash Flow Yield (CF/Y) |
| dy | Dividend Yield (DY) |
| gpa | Gross Profitability (GPA) |
| wca | Working Capital Ratio (WCA) |
| ltde | Negative Leverage (LTDE) |
| roa | Return on Assets (ROA) |
| z_bp … z_roa | Sector-neutral inverse-normal z-scores for each metric |
| value_score | Dimension z-score for Value (B/P, E/Y, CF/Y, DY) |
| quality_score | Dimension z-score for Quality (GPA, WCA, LTDE, ROA) |
| composite_score | Universe z-score: 50% Value + 50% Quality |
| composite_percentile | Rank / N (0–1); higher = better |
| quintile | Q1 (top 20%, best) to Q5 (bottom 20%, worst) |

## Results

| Year | Companies loaded | Eligible | Composite scores | Notes |
|---|---|---|---|---|
| 2021 | 101 | 1 | 0 | yfinance 4-year limit; 2021 data mostly unavailable |
| 2022 | 583 | 181 | 181 | Partial data for Dec FY-end companies |
| 2023 | 596 | 428 | 428 | ~85–86 per quintile |
| 2024 | 597 | 435 | 435 | ~87 per quintile |
| 2025 | 597 | 430 | 430 | ~86 per quintile |

## Infrastructure Ports

| Service     | External Port | Credentials                  |
|-------------|---------------|------------------------------|
| PostgreSQL  | 5439          | postgres / postgres          |
| MongoDB     | 27019         | none                         |
| MinIO API   | 9000          | ift_bigdata / minio_password |
| MinIO UI    | 9001          | ift_bigdata / minio_password |
| PgAdmin     | 5051          | admin@admin.com / root       |
| Kafka       | 9092          | none                         |
