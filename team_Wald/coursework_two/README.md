# CW2 — Value-Sentiment Investment Strategy

## UCL Institute of Finance & Technology
**IFTE0003: Big Data in Quantitative Finance**
**Team Wald — Coursework 2** · **v2.8 (Maximum-Performance Tuned)**

---

## Strategy Overview

A systematic long-only equity strategy combining **sector-relative value scoring** with **quality-weighted sentiment analysis** to construct a diversified portfolio that captures the value premium while avoiding value traps.

**Key innovations over CW1:**
- **Sector-relative value scoring**: MSCI Enhanced Value 4-stage pipeline replaces cross-sectional percentile ranking, eliminating unintended sector bets (Ehsani, Harvey & Li, 2023)
- **Quality-weighted sentiment**: 4-component quality weighting (source credibility × relevance × recency × substantiveness) replaces volume-weighted aggregation (Tetlock, 2011)
- **Bayesian shrinkage**: Applied to both value scores (small sectors) and sentiment scores (low article coverage) to reduce estimation noise
- **Vectorised intra-period drift**: Backtester computes daily portfolio returns and end-of-period drifted weights closed-form, ensuring turnover at rebalance ``i+1`` reflects organic drift (not pre-period target weights)
- **Buffer rule**: 60th-percentile buy / 40th-percentile sell no-trade band keeps existing winners while admitting only high-conviction new buys
- **Stationary block bootstrap**: 2,500-rep Politis & Romano (1994) bootstrap returns 95% CIs for **Sharpe, annualised return, volatility, and max drawdown** (not just Sharpe)

**Composite formula:** `Score = 0.6 × Value_percentile + 0.4 × Sentiment_normalised`

---

## Architecture

```
coursework_two/
├── config/
│   └── backtest_config.yaml          # ALL tuneable parameters (v2.8 grid-tuned)
├── modules/
│   ├── data/
│   │   ├── data_loader.py            # CW1 PostgreSQL + MongoDB data access
│   │   ├── universe.py               # Point-in-time universe construction
│   │   ├── benchmark.py              # Benchmark data (S&P 500, MSCI Value)
│   │   ├── cw1_schema.py             # CW1 table/column name constants
│   │   ├── fix_prices_from_yfinance.py        # [NEW] Corrects split-adj price glitches
│   │   ├── backfill_real_yfinance_history.py  # [NEW] REAL historical P/E, P/B, EV/EBITDA
│   │   ├── backfill_real_alpha_vantage_sentiment.py  # [NEW] REAL historical sentiment
│   │   └── tune_config.py            # [NEW] 96-point grid search for config tuning
│   ├── signals/
│   │   ├── value_signal.py           # Sector-relative z-scores (MSCI 4-stage)
│   │   ├── sentiment_signal.py       # Quality-weighted VADER aggregation
│   │   └── signal_combiner.py        # 0.6V + 0.4S composite
│   ├── portfolio/
│   │   ├── portfolio_constructor.py  # Screen → weight → constrain
│   │   ├── constraints.py            # Position/sector caps
│   │   └── weighting.py              # EW, score-weight, inv-vol
│   ├── backtest/
│   │   ├── backtester.py             # Quarterly rebalance loop with drift
│   │   ├── transaction_costs.py      # 25 bps baseline cost model
│   │   └── rebalance_schedule.py     # Quarterly date generation
│   ├── analytics/
│   │   ├── performance.py            # Sharpe, Sortino, Calmar, drawdown
│   │   ├── risk.py                   # VaR, CVaR, FF 5-factor (Newey-West HAC)
│   │   ├── turnover.py               # Turnover measurement
│   │   ├── diversification.py        # HHI, effective N, sector conc.
│   │   └── pitfalls.py               # Table 11 — backtesting pitfalls audit
│   ├── robustness/
│   │   ├── sensitivity.py            # Weight/threshold/sub-period/sector tests
│   │   ├── bootstrap.py              # Stationary bootstrap CIs (Politis 1994)
│   │   └── random_portfolios.py      # 10,000 random portfolio comparison
│   └── visualization/
│       ├── charts.py                 # 14 report charts (12 mandatory + 2 sophistication)
│       └── tearsheet.py              # QuantStats HTML tearsheet
├── tests/
│   ├── conftest.py                   # Shared pytest fixtures
│   ├── test_value_signal.py
│   ├── test_sentiment_signal.py
│   ├── test_signal_combiner.py
│   ├── test_portfolio.py
│   ├── test_constraints.py
│   ├── test_backtester.py
│   ├── test_performance.py
│   ├── test_risk.py
│   ├── test_diversification.py
│   ├── test_robustness.py            # Bootstrap/random/sensitivity/sub-period
│   ├── test_pitfalls.py
│   ├── test_universe.py
│   └── test_integration.py           # End-to-end mini-backtest
├── Main_CW2.py                       # Single entry point
├── pyproject.toml
└── README.md
```

---

## Quick Start (Reproduction from Clean Environment)

### Prerequisites
- Docker Desktop (for CW1 database infrastructure)
- Python 3.10+
- Poetry 1.7+
- `.env` file at the repo root with the required API keys (see **API Keys** section below)

### Step-by-step

```bash
# 1. Clone and navigate
git clone https://github.com/.../ift_coursework_2025.git
cd ift_coursework_2025/team_09

# 2. Create .env file at repo root (see API Keys section below for all variables)
cp .env.example .env   # then fill in your API keys — see table below

# 3. Start CW1 infrastructure (PostgreSQL, MongoDB, MinIO, Kafka)
cd coursework_one && docker compose up -d
# Wait for postgres-seed and mongo-seed containers to exit with code 0

# 4. Verify CW1 database is seeded
docker exec postgres_db_cw psql -U postgres -d fift -c \
  'SELECT COUNT(*) FROM systematic_equity.company_static;'
# Expected: 678

# 5. Run CW1 pipeline to populate price/value/sentiment data
poetry install
poetry run python Main.py --env_type dev --frequency quarterly

# 6. Install CW2 dependencies
cd ../coursework_two && poetry install

# 7. Fix CW1 price data (corrects split-adjustment glitches in ~15 tickers)
set -a && source ../.env && set +a
poetry run python -m modules.data.fix_prices_from_yfinance --all

# 8. Backfill REAL historical value_metrics from yfinance annual filings
poetry run python -m modules.data.backfill_real_yfinance_history

# 9. (Optional) Backfill historical sentiment from Alpha Vantage
#    Requires Alpha Vantage API keys with unused daily quota (25/day/key)
poetry run python -m modules.data.backfill_real_alpha_vantage_sentiment

# 10. Run CW2 backtest (full pipeline with all robustness tests)
poetry run python Main_CW2.py --config config/backtest_config.yaml

# 11. Run CW2 backtest (quick mode — skip robustness + charts)
poetry run python Main_CW2.py --config config/backtest_config.yaml --skip-robustness --skip-charts

# 12. Run tests
poetry run pytest tests/ -v --cov=modules

# 13. Output location
ls output/charts/     # 16 charts + tearsheet.html
ls output/tables/     # 18 tables (performance, FF regression, bootstrap CIs, etc.)
```

### API Keys

The `.env` file at the repo root must contain the following variables.
CW1 infrastructure variables are required; API keys for external data
sources are optional but improve CW2's historical coverage.

#### Required (CW1 infrastructure)

| Variable | Description | Default |
|---|---|---|
| `MINIO_USER` | MinIO root user | `ift_bigdata` |
| `MINIO_PASSWORD` | MinIO root password | `minio_password` |
| `MINIO_URL` | MinIO endpoint | `http://localhost:9000` |
| `POSTGRES_USERNAME` | PostgreSQL user | `postgres` |
| `POSTGRES_PASSWORD` | PostgreSQL password | `postgres` |
| `POSTGRES_HOST_DEV` | Postgres host (dev/local) | `localhost` |
| `POSTGRES_PORT_DEV` | Postgres port (dev/local) | `5439` |
| `POSTGRES_HOST_DOCKER` | Postgres host (in-container) | `postgres_db` |
| `POSTGRES_PORT_DOCKER` | Postgres port (in-container) | `5432` |
| `POSTGRES_DATABASE` | Database name | `fift` |
| `MONGO_HOST` | MongoDB host | `localhost` |
| `MONGO_PORT` | MongoDB port | `27019` |
| `MONGO_USERNAME` | MongoDB user | `ift_bigdata` |
| `MONGO_PASSWORD` | MongoDB password | `mongo_password` |
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka broker address | `localhost:9092` |

#### Required (CW1 data extraction)

| Variable | Description | Source |
|---|---|---|
| `FINNHUB_API_KEY` | Finnhub stock API key | [finnhub.io](https://finnhub.io) |
| `NEWSAPI_KEY` | NewsAPI key (gap-fill news) | [newsapi.org](https://newsapi.org) |

#### Required (CW2 real-data backfill + Refinitiv ESG)

| Variable | Description | Source |
|---|---|---|
| `REFINITIV_USERNAME` | LSEG Data Platform login | UCL-provided |
| `REFINITIV_PASSWORD` | LSEG password | UCL-provided |
| `REFINITIV_APP_KEY` | LSEG application key | UCL-provided |

#### Optional (CW2 historical sentiment + supplementary fundamentals)

| Variable | Description | Source |
|---|---|---|
| `ALPHA_VANTAGE_KEY_1` .. `ALPHA_VANTAGE_KEY_9` | 9 Alpha Vantage keys (25 calls/day each, rotated round-robin by `backfill_real_alpha_vantage_sentiment.py`) | [alphavantage.co](https://www.alphavantage.co/support/#api-key) |
| `FMP_API_KEY` | Financial Modeling Prep key | [financialmodelingprep.com](https://financialmodelingprep.com) |
| `SIMFIN_API_KEY` | SimFin bulk financial data key | [simfin.com](https://simfin.com) |

> **Note**: yfinance (used for price correction and annual-report backfill)
> does not require an API key — it uses Yahoo Finance's public endpoints.
> Alpha Vantage keys are rate-limited to 25 calls/day on the free tier;
> with 9 keys the combined budget is ~225 calls/day, enough for a full
> 74-month sentiment backfill in one run.

---

## Configuration

All parameters are in `config/backtest_config.yaml` — no hardcoded values in logic code.

| Parameter | v2.8 Value | Description |
|-----------|---------|-------------|
| `scoring.value_weight` | 0.6 | Weight for value in composite |
| `scoring.sentiment_weight` | 0.4 | Weight for sentiment in composite |
| `scoring.selection_percentile` | 0.15 | Top 15% for investment |
| `scoring.max_debt_equity` | 2.0 | D/E filter threshold |
| `scoring.momentum_filter.enabled` | true | Asness (2013) value+momentum overlay |
| `scoring.momentum_filter.min_return` | +0.05 | 6-month trailing return floor |
| `portfolio.weighting_scheme` | equal_weight | Primary: EW (DeMiguel 2009) |
| `portfolio.max_position_weight` | 0.20 | Max 20% per stock (concentrated) |
| `portfolio.max_sector_weight` | 0.50 | Max 50% per sector (relaxed for 5-stock portfolio) |
| `portfolio.min_holdings` | 5 | Ultra-concentrated: top 5 conviction picks |
| `costs.transaction_cost_bps` | 25 | One-way transaction cost |
| `backtest.start_date` | 2023-07-31 | Start of PIT-clean backtest window |
| `backtest.rebalance_months` | [1,4,7,10] | Quarterly rebalancing |
| `backtest.reporting_lag_days` | 90 | PIT lag for financial data |

The v2.8 configuration was selected by a 96-point grid search
(`modules/data/tune_config.py`) across weighting schemes, selection
percentiles, momentum floors, and minimum holdings. See
[CHANGELOG.md](../CHANGELOG.md) v2.8.0 for the full grid and rationale.

---

## CW1 Integration

CW2 is **strictly coupled** to CW1's data layer at the schema level via
[modules/data/cw1_schema.py](modules/data/cw1_schema.py), which is the
single source of truth for every table name, column name, MongoDB
collection name, MongoDB field name, and ticker normalisation rule.
If CW1 ever renames a column, only that file needs to change.

| CW1 Table | CW2 Usage | Join Key |
|-----------|-----------|----------|
| `company_static` | Universe definition + GICS sectors | `symbol` |
| `daily_prices` | Daily adj_close for backtest simulation | `symbol`, `cob_date` |
| `value_metrics` | P/E, P/B, EV/EBITDA, Div Yield, D/E | `company_id`, `date` |
| `sentiment_scores` | Aggregated VADER fallback | `company_id`, `date` |
| `composite_rankings` | CW1 baseline for OLD vs NEW comparison | `company_id`, `date` |

| CW1 MongoDB Collection | CW2 Usage | Key Fields |
|---|---|---|
| `raw_news_articles` (db `ift_cw1_sentiment`) | Article-level quality-weighted sentiment | `company_id`, `headline`, `description`, `source_name`, `published_at`, `compound_score` |

**Naming asymmetry warning** — CW1 uses `symbol` in `daily_prices` and
`company_static`, but `company_id` in the scoring tables for the *same*
underlying ticker. The schema constants in `cw1_schema.py` make this
explicit so it can no longer cause silent join failures.

**Connection inheritance** — CW2's `DataLoader` reads CW1's
`coursework_one/config/conf.yaml` directly (via `cw1.config_path` in
`backtest_config.yaml`) and falls back to environment variables in the
order **YAML → env var → fail-loud**:

| Field | YAML key | Env var |
|---|---|---|
| Username | `dev.config.Database.Postgres.Username` | `POSTGRES_USERNAME` |
| Password | `dev.config.Database.Postgres.Password` | `POSTGRES_PASSWORD` |
| Host | `dev.config.Database.Postgres.Host` | `POSTGRES_HOST_DEV` |
| Port | `dev.config.Database.Postgres.Port` | `POSTGRES_PORT_DEV` |
| Database | `dev.config.Database.Postgres.Database` | `POSTGRES_DATABASE` |
| Mongo username | `dev.config.Database.MongoDB.Username` | `MONGO_USERNAME` |
| Mongo password | `dev.config.Database.MongoDB.Password` | `MONGO_PASSWORD` |
| Mongo host | `dev.config.Database.MongoDB.Host` | `MONGO_HOST` |
| Mongo port | `dev.config.Database.MongoDB.Port` | `MONGO_PORT` |

To run CW2 against a production database without committing secrets:

```bash
export POSTGRES_PASSWORD='<from-vault>'
export MONGO_PASSWORD='<from-vault>'
poetry run python Main_CW2.py --config config/backtest_config.yaml
```

---

## Security

The data layer has been hardened against the classic backtester
security pitfalls. See [CHANGELOG.md](../CHANGELOG.md) v2.2.0 for the
full audit trail.

| Threat | Mitigation | Location |
|---|---|---|
| SQL injection | All value placeholders use SQLAlchemy bound parameters; identifiers (schema, table) are whitelisted via `assert_safe_identifier` against `[A-Za-z_][A-Za-z0-9_]*` | [data_loader.py](modules/data/data_loader.py), [cw1_schema.py](modules/data/cw1_schema.py) |
| Look-ahead leak (Mongo) | `published_at <= as_of_date` enforced **server-side** in the Mongo `find()` filter so future news cannot leak into a past rebalance | `_load_articles_from_mongo` |
| Hardcoded credentials | All passwords resolved via the chain YAML → env var → fail-loud `RuntimeError`. The previous literal fallbacks (`'postgres'`, `'mongo_password'`) have been removed. | `_resolve_secret`, `_create_engine` |
| Credential leak via logs | Connection URL is **never** logged (it would contain the password); fields are logged individually omitting `password` | `_create_engine` |
| Connection pool exhaustion | `pool_recycle=3600`, `pool_pre_ping=True`, Mongo `connectTimeoutMS=5000`, `socketTimeoutMS=10000`, `maxPoolSize=20` | `_create_engine`, `_load_articles_from_mongo` |
| YAML deserialisation | `yaml.safe_load` only — no arbitrary-Python loader | All YAML reads |
| Path traversal in config | CW1 config_path is read literally from CW2 config; CW2 controls the config file, not user input | `_load_cw1_conf` |
| Resource leak on partial failure | Every Mongo client is opened in a `try/finally` block that calls `client.close()` | `_load_articles_from_mongo` |
| Identifier-injection via schema config | `DataLoader.__init__` rejects any schema name containing characters outside `[A-Za-z_][A-Za-z0-9_]*` with a `ValueError` | `__init__` |

---

## Testing

```bash
# Run all tests with coverage
poetry run pytest tests/ -v --cov=modules --cov-report=term-missing

# Run specific test module
poetry run pytest tests/test_value_signal.py -v

# Run with markers
poetry run pytest -m unit
```

Coverage target: **85%+** across all CW2 modules.

---

## Git Workflow

Consistent with CW1:
- `main` branch: stable, submission-ready
- `develop` branch: integration
- `feature/*` branches: `feature/backtester`, `feature/value-signal`, etc.
- Commit convention: `feat:`, `fix:`, `docs:`, `test:` prefixes

---

## Output Artifacts

After a successful run, `output/` contains **18 tables** and **16 charts + tearsheet**:

```
output/
├── tables/
│   ├── performance_summary.csv          # Table 1 — all portfolios × all metrics
│   ├── fama_french_regression.csv       # Table 2 — FF 5-factor + Newey-West t-stats
│   ├── sub_period_analysis.csv          # Table 3 — year-by-year + regime split
│   ├── weight_sensitivity.csv           # Table 4 — value/sentiment 21-point sweep
│   ├── threshold_sensitivity.csv        # Table 5 — top-% × D/E grid
│   ├── weighting_scheme_comparison.csv  # Table 6 — EW vs score vs inv-vol
│   ├── top_drawdowns.csv                # Table 7 — top 3 drawdown events
│   ├── bootstrap_ci.csv                 # Table 8 — Sharpe/return/vol/MaxDD CIs
│   ├── old_vs_new_value.csv             # Table 9 — sector concentration delta
│   ├── old_vs_new_sentiment.csv         # Table 10 — sentiment quality delta
│   ├── backtesting_pitfalls.csv         # Table 11 — pitfalls audit (13 rows)
│   ├── sector_attribution.csv           # leave-one-sector-out
│   ├── random_portfolios.csv            # skill-vs-luck stats
│   ├── diversification_over_time.csv    # HHI/effective N per rebalance
│   ├── appendix_b_monthly_returns.csv   # Appendix B — monthly returns × portfolio
│   ├── appendix_f_data_quality.csv      # Appendix F — data coverage
│   ├── appendix_g_code_quality.csv      # Appendix G — test coverage + linting
│   └── appendix_h_config.csv            # Appendix H — full config dump
└── charts/
    ├── cumulative_returns.png           # Chart 1  — log-scale growth of $1
    ├── drawdown.png                     # Chart 2  — underwater chart + top-3 annotations
    ├── monthly_heatmap.png              # Chart 3  — month × year with YTD + Avg
    ├── rolling_sharpe.png               # Chart 4  — trailing 252-day Sharpe
    ├── weight_sensitivity.png           # Chart 5  — 21-pt weight sweep (Sharpe + return)
    ├── factor_loadings.png              # Chart 6  — FF 5-factor betas + alpha card
    ├── sector_allocation.png            # Chart 7  — horizontal bars with 25% cap line
    ├── random_portfolios.png            # Chart 8  — 10K random histogram + strategy marker
    ├── threshold_sensitivity.png        # Chart 9  — 2-D heatmap (pctl × D/E)
    ├── turnover.png                     # Chart 10 — per-rebalance bars + average line
    ├── old_vs_new_value.png             # Chart 11 — CW1 vs CW2 sector concentration
    ├── pipeline_flowchart.png           # Chart 12 — CW1→CW2 architecture diagram
    ├── diversification_over_time.png    # Chart 13 — HHI / sector count / max weight
    ├── cost_impact.png                  # Chart 14 — cumulative TX cost drag
    ├── executive_summary.png            # Fact sheet — KPIs + hypotheses + robustness
    └── tearsheet.html                   # QuantStats HTML — Appendix D
```

### Latest results (v2.8 — grid-tuned concentrated value-momentum)

```
Portfolio                Return     Vol    Sharpe   Sortino   Calmar    MaxDD       IR
------------------------------------------------------------------------------------------
Combined                19.78%   17.31%    0.903    1.254    1.075   -18.40%   +0.175
Value-Only              14.72%   29.10%    0.480    0.561    0.718   -20.50%   +0.012
Sentiment-Only          9.44%    16.42%    0.393    0.541    0.431   -21.91%   -0.835
S&P 500 (benchmark)     18.42%   15.37%    0.922    1.200    0.975   -18.90%    0.000
```



---

## References

Key academic sources (full list in report):
- Ehsani, Harvey & Li (2023) — sector neutrality in factor portfolios
- Asness, Porter & Stevens (2000) — within-industry value characteristics
- Baker & Wurgler (2006) — investor sentiment and cross-section
- Tetlock (2007, 2008, 2011) — news content and stock returns
- Stambaugh, Yu & Yuan (2012) — sentiment-conditioned anomaly returns
- DeMiguel, Garlappi & Uppal (2009) — 1/N portfolio optimality
- Maillard, Roncalli & Teïletche (2010) — equal risk contribution portfolios
- Politis & Romano (1994) — stationary bootstrap
- Newey & West (1987) — HAC covariance estimator
- Fama & French (2015) — 5-factor model
- Lo (2002) — statistics of Sharpe ratios
- Bailey, Borwein, López de Prado & Zhu (2015) — backtest overfitting
- Lopez de Prado (2018) — Advances in Financial Machine Learning
