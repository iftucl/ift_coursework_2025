# Team Luzin - Coursework One: Investment Strategy Data Pipeline

![Python](https://img.shields.io/badge/python-3.10+-blue)
![Poetry](https://img.shields.io/badge/Poetry-managed-blue)
![Tests](https://img.shields.io/badge/coverage-85%25-brightgreen)

## Overview

A production-grade data pipeline for quantitative investment strategy development. Processes 678+ stocks through a 4-step pipeline to deliver trading signals and ranked portfolio recommendations.

**Pipeline Flow**: 
```
Company Universe (678) 
  → Data Availability (597) 
  → Portfolio Selection (130) 
  → Execution Signals (335 BUY) 
  → MinIO Export
```

## Quick Start

### 1. Installation

```bash
cd team_luzin/coursework_one
poetry install
```

### 2. Configure

Edit `config/conf.yaml` with PostgreSQL and MinIO credentials:

```yaml
postgres:
  host: "localhost"
  port: 5439
  database: "fift"
  user: "postgres"
  password: "postgres"

minio:
  endpoint: "localhost:9000"
  access_key: "minioadmin"
  secret_key: "minioadmin"
  bucket: "csreport"
```

### 3. Run Pipeline

```bash
# Default: daily frequency
poetry run python3 run_pipeline.py

# Specify frequency
poetry run python3 run_pipeline.py --frequency weekly

# Backfill specific date
poetry run python3 run_pipeline.py --run-date 2026-03-01

# Dry-run (no database writes)
poetry run python3 run_pipeline.py --dry-run
```

## Project Structure

```
team_luzin/coursework_one
│
├── config/
│   └── conf.yaml                          # Database & MinIO credentials
│
├── modules/                               # Core data processing modules
│   │
│   ├── db/
│   │   └── postgres_connector.py          # PostgreSQL connection & queries
│   │
│   ├── input/
│   │   ├── __init__.py
│   │   └── market_data_loader.py          # Data downloading & validation
│   │
│   ├── extraction/
│   │   ├── __init__.py
│   │   └── price_extractor.py             # Price data extraction utilities
│   │
│   ├── processing/
│   │   ├── risk.py                        # VAR_95 & ATR_14 calculations
│   │   ├── momentum.py                    # Technical momentum indicators
│   │   ├── liquidity.py                   # Liquidity scoring
│   │   ├── composite_scoring.py           # Portfolio selection algorithm
│   │   ├── trend.py                       # Trend analysis
│   │   └── __init__.py
│   │
│   ├── signals/
│   │   ├── __init__.py
│   │   └── execution_signals.py           # MACD, ATR, liquidity signals
│   │
│   ├── data/
│   │   ├── __init__.py
│   │   └── sector_filter.py               # Sector filtering utilities
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── datalake_writer.py             # Data lake publishing
│   │   ├── minio_storage.py               # MinIO S3 client wrapper
│   │   └── parquet_reader.py              # Parquet file utilities
│   │
│   ├── output/
│   │   ├── __init__.py
│   │   └── export_analytics.py            # Analytics export & formatting
│   │
│   └── __init__.py
│
├── pipeline/                              # 4-step pipeline scripts
│   │
│   ├── calculate_var_all_stocks.py        # Step 1: Risk metrics
│   ├── calculate_composite_portfolio.py   # Step 2: Portfolio selection
│   ├── trading_execution.py               # Step 3: Signal generation
│   ├── export_analytics_to_minio.py       # Step 4: MinIO export
│   │
│   └── Utilities:
│       ├── clean_fresh_run.py             # Cache cleanup + full run
│       └── select_portfolio.py            # Portfolio selection utility
│
├── static/
│   └── example_outputs/
│       └── README.md                      # Sample output documentation
│
├── test/                                  # 13+ test files (80%+ coverage)
│   ├── test_var.py
│   ├── test_portfolio.py
│   ├── test_signals.py
│   ├── test_momentum.py
│   ├── test_risk.py
│   ├── test_liquidity.py
│   ├── test_trend.py
│   └── ... (more test files)
│
├── main.py                                # Primary entry point (thin wrapper)
├── run_pipeline.py                        # Pipeline orchestrator with CLI
│
├── pyproject.toml                         # Poetry dependencies (30+ packages)
├── pytest.ini                             # Test configuration
├── .gitignore                             # Git ignore rules
├── README.md                              # This file
├── CHANGELOG.md                           # Version history
│
└── docs/                                  # Sphinx documentation
    ├── conf.py
    ├── index.rst
    ├── quickstart.rst
    ├── architecture.rst
    ├── testing.rst
    ├── code_quality.rst
    ├── deployment.rst
    └── _build/                            # Generated HTML docs
```

## Pipeline Architecture

### Step 1: VaR & ATR Calculation
**Script**: `calculate_var_all_stocks.py`

Calculates risk metrics for all stocks:
- Downloads 252 days of price data from yfinance
- Computes 95% confidence Value-at-Risk (VaR_95)
- Computes 14-day Average True Range (ATR_14)

| Metric | Value |
|--------|-------|
| Input Stocks | 678 |
| Successful | 597 (88.1%) |
| Processing Time | ~1:47 |
| Rate | 6.2 stocks/sec |

### Step 2: Portfolio Selection
**Script**: `calculate_composite_portfolio.py`

Selects best stocks using composite scoring:
- **Score Formula**: Z(RAM) + Z(Liquidity) - Z(VaR)
  - Z(RAM): Risk-Adjusted Momentum z-score
  - Z(Liquidity): 60-day avg volume z-score
  - Z(VaR): 95% confidence tail risk z-score
- **Quality Filters**:
  - Liquidity > $1M daily average
  - Positive momentum
  - Valid risk metrics

| Metric | Value |
|--------|-------|
| Input Stocks | 597 |
| Selected | 130 (top composite scores) |
| Score Range | -11.26 to 4.03 |
| Avg Score | 2.19 |
| Processing Time | ~0.25s |

**Exports**:
- `analytics/portfolio/portfolio_YYYYMMDD.parquet|csv` (full details)
- `analytics/selections/selections_YYYYMMDD.parquet|csv` (ranked 1-130)

### Step 3: Execution Signals
**Script**: `trading_execution.py`

Generates MACD-based trading signals:
- **Entry Signal**: MACD > MACD_Signal (bullish crossover)
- **Exit Signal**: MACD < MACD_Signal (bearish crossover)
- **Strength**: MACD_Histogram positive (momentum confirmation)

| Metric | Value |
|--------|-------|
| Input Stocks | 597 |
| BUY Signals | 346 (57.9%) |
| SELL Signals | 252 (42.1%) |
| Final BUY (final_trade_signal=1) | 335 |

**Note**: Execution signals are INDEPENDENT of portfolio selection. Not all 130 selected stocks have bullish MACD, and not all 335 BUY signals are in the top 130.

### Step 4: Data Lake Publishing
**Script**: `export_analytics_to_minio.py`

Exports analytics to MinIO data lake with three-layer architecture:

```
MinIO Data Lake Structure (s3://csreport/):
analytics/
├── raw/
│   └── prices/                            # Raw price cache (600 stock files)
│
├── processed/
│   ├── step1/
│   │   ├── 20260315_182019/
│   │   │   ├── factors_20260315_182019.parquet
│   │   │   └── factors_20260315_182019.csv
│   │   ├── factors_latest.parquet
│   │   └── factors_latest.csv             # Latest alias (Step 1 factors)
│   │
│   ├── step2/
│   │   ├── 20260315_182019/
│   │   │   ├── portfolio_20260315_182019.parquet
│   │   │   ├── selections_20260315_182019.parquet
│   │   │   └── (CSV versions)
│   │   ├── portfolio_latest.*
│   │   └── selections_latest.*            # Latest aliases (Step 2)
│   │
│   └── step3/
│       ├── 20260315_182019/
│       │   ├── signals_20260315_182019.parquet
│       │   └── signals_20260315_182019.csv
│       ├── signals_latest.parquet
│       └── signals_latest.csv             # Latest alias (Step 3 signals)
│
└── serving/
    ├── portfolio/portfolio_latest.csv     # Latest portfolio (for consumption)
    ├── selections/selections_latest.csv   # Latest selections
    └── signals/signals_latest.csv         # Latest signals
```

**Publishing Strategy:**
- **raw/**: Original price cache from local analytics/raw/prices/
- **processed/**: Timestamped versions (YYYYMMDD_HHMMSS) + latest aliases for reproducibility
- **serving/**: Read-only latest CSVs for downstream consumption

## Data Outputs

### Signals Export (10 columns, 597 records)
```
symbol, macd, macd_signal, macd_histogram, macd_trend_signal,
atr_14, atr_risk_signal, liquidity_signal, risk_signal, final_trade_signal
```

### Portfolio Export (15 columns, 335 BUY records)
```
symbol, gics_sector, gics_industry, country, region,
momentum_252, volatility_252, risk_adjusted_momentum_252, volume_60d_avg, var_95,
z_momentum, z_liquidity, z_var, composite_score, composite_rank
```

### Selections Export (4 columns, 130 ranked records)
```
symbol, gics_sector, composite_score, composite_rank (1-130)
```

## Testing

### Run All Tests
```bash
poetry run pytest test/ -v --cov=modules
```

### Coverage Report
```bash
poetry run pytest test/ --cov=modules --cov-report=html
open htmlcov/index.html
```

**Coverage Goal**: 80%+ | **Actual**: 85%+

## Code Quality

### Format Code
```bash
poetry run black modules/
poetry run isort modules/
```

### Lint Code
```bash
poetry run flake8 modules/ --max-line-length=88
```

### Security Scan
```bash
poetry run bandit -r modules/ -ll
```

## Documentation

### Sphinx Documentation
```bash
poetry run sphinx-build -b html docs/ docs/_build/
open docs/_build/index.html
```

### API Reference
See `docs/api.rst` for complete module documentation.

### Architecture
See `docs/architecture.rst` for system design and data flow.

## Project Structure

```
coursework_one/
├── CHANGELOG.md                 # Version history (v1.0 → v2.0)
├── README.md                    # This file
├── pyproject.toml              # Poetry configuration
│
├── config/
│   └── conf.yaml               # Database & MinIO settings
│
├── modules/                    # Reusable components
│   ├── db/
│   │   └── postgres_connector.py
│   ├── processing/
│   │   ├── risk.py            # VAR & ATR calculations
│   │   └── composite_scoring.py
│   ├── storage/
│   │   └── minio_storage.py
│   └── __init__.py
│
├── test/                       # pytest suite (80%+ coverage)
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_risk.py
│   │   └── test_scoring.py
│   ├── integration/
│   │   └── test_pipeline.py
│   └── fixtures/
│       └── sample_data.py
│
├── static/                     # Static resources
│   └── sample_config.yaml
│
├── docs/                       # Sphinx documentation
│   ├── conf.py
│   ├── index.rst
│   ├── api.rst
│   └── architecture.rst
│
├── run_pipeline.py            # Main orchestrator (CLI)
├── calculate_var_all_stocks.py
├── calculate_composite_portfolio.py
├── trading_execution.py
├── export_analytics_to_minio.py
│
└── .gitignore
```

## Dependencies

**Core Libraries**:
- psycopg2-binary: PostgreSQL
- minio: S3-compatible storage
- pyyaml: Configuration
- yfinance: Stock prices
- pandas: Data processing
- pyarrow: Parquet format
- numpy: Numerical computing
- tqdm: Progress bars

**Development**:
- pytest: Testing framework
- pytest-cov: Coverage reporting
- black: Code formatting
- flake8: Linting
- isort: Import sorting
- bandit: Security scanning
- sphinx: Documentation

See `pyproject.toml` for complete list and versions.

## Configuration

### Environment Variables
```bash
export PG_HOST=localhost
export PG_PORT=5439
export MINIO_ENDPOINT=localhost:9000
```

### YAML Configuration (config/conf.yaml)
```yaml
postgres:
  host: "localhost"
  port: 5439
  database: "fift"
  user: "postgres"
  password: "postgres"
  schema: "systematic_equity"

minio:
  endpoint: "localhost:9000"
  access_key: "minioadmin"
  secret_key: "minioadmin"
  bucket: "csreport"
```

## Performance

| Operation | Time | Rate |
|-----------|------|------|
| VAR Calculation (597 stocks) | 1:47 | 6.2 stocks/sec |
| Portfolio Selection (597→130) | 0.25s | - |
| Signal Generation (MACD) | 2s | - |
| MinIO Upload (4 files) | 0.5s | - |
| **Total Pipeline** | **~2 min** | - |

## Scheduling

### Daily Execution (Cron)
```bash
0 9 * * * cd /path/to/coursework_one && poetry run python3 run_pipeline.py --frequency daily
```

### Weekly Execution (Cron)
```bash
0 9 * * 1 cd /path/to/coursework_one && poetry run python3 run_pipeline.py --frequency weekly
```

### With APScheduler
```python
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()
scheduler.add_job(run_pipeline, 'interval', hours=24)
scheduler.start()
```

## Troubleshooting

### PostgreSQL Connection
```bash
# Check PostgreSQL is running
docker ps | grep postgres

# Verify connection
psql -h localhost -p 5439 -U postgres -d fift -c "SELECT 1"
```

### MinIO Connection
```bash
# Check MinIO is running
docker ps | grep minio

# Verify bucket
aws s3 ls s3://csreport --endpoint-url http://localhost:9000
```

### yfinance Errors
Some stocks may be delisted (normal). Check logs:
```bash
tail -f clean_fresh_run.log
```

## Development Workflow

### 1. Create Feature Branch
```bash
git checkout -b feature/my-feature
```

### 2. Write Tests
```bash
poetry run pytest test/ -v
```

### 3. Implement Feature
```bash
# Implement in modules/
```

### 4. Run Quality Checks
```bash
poetry run flake8 modules/
poetry run black modules/
poetry run bandit -r modules/
```

### 5. Update Documentation
```bash
# Add docstrings and update docs/
```

### 6. Submit PR
```bash
git push origin feature/my-feature
# Open PR to @uceslc0 for review
```

## Security Practices

✅ **Implemented**:
- Secrets stored in `config/conf.yaml` (not committed)
- Input validation on all data
- SQL injection prevention with psycopg2 parameterized queries
- TLS for database connections
- Regular vulnerability scanning with bandit

✅ **Scanning**:
```bash
poetry run bandit -r modules/ -ll
poetry check --lock  # Check dependencies
```

## Git Workflow

### Repository
- **GitHub**: https://github.com/iftucl/ift_coursework_2025
- **Branch**: team_luzin/coursework_one
- **Assigned to**: @uceslc0

### Before Committing
1. Never modify `/000.Database/`
2. Only commit changes in `/team_luzin/`
3. Run quality checks
4. Ensure tests pass
5. Update CHANGELOG.md

### Submission Checklist
- ✅ Code passes flake8, black, isort
- ✅ Security: Passes bandit scan
- ✅ Testing: 85%+ coverage with pytest
- ✅ Documentation: Full Sphinx docs
- ✅ Configuration: YAML-based, secrets safe
- ✅ Scheduling: CLI arguments for flexible execution
- ✅ Git: Clean history, only team_luzin/ modified

## References

- **PostgreSQL**: localhost:5439 (systematic_equity schema)
- **MinIO**: localhost:9000 (csreport bucket)
- **MongoDB**: localhost:27019 (optional)
- **Company Table**: company_static (678 stocks)
- **Metrics Table**: momentum_factors

## License

See LICENSE file in repository root.

## Support

- 📖 Documentation: See `docs/` folder
- 🧪 Tests: See `test/` folder
- 📝 Logs: Check pipeline output
- 🐛 Issues: Review test cases for examples

---

**Status**: Production-Ready | **Version**: 2.0.0 | **Last Updated**: 2026-03-08
