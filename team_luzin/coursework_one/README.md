# Team Luzin - Coursework One: Investment Strategy Data Pipeline

A systematic data pipeline for building investment indicators and portfolio construction. Processes 600+ securities through a 4-stage pipeline to deliver risk metrics, portfolio selections, and trading signals.

## Quick Start

### Installation
```bash
poetry install
```

### Configuration
Edit `config/conf.yaml` with PostgreSQL credentials:
```yaml
postgres:
  host: localhost
  port: 5439
  database: fift
  schema: systematic_equity
```

### Run Pipeline
```bash
# Default (daily)
poetry run python3 main.py

# Other frequencies
poetry run python3 main.py --frequency weekly
poetry run python3 main.py --run-date 2026-03-15
poetry run python3 main.py --dry-run
```

---

## Pipeline Stages

| Stage | Description | Output |
|-------|-------------|--------|
| 1 | Risk Metrics (VAR_95, ATR_14) | 598 stocks × risk factors |
| 2 | Portfolio Selection | 110-130 selected stocks |
| 3 | Trading Signals (MACD, ATR) | BUY/SELL/HOLD signals |
| 4 | Export & Storage | CSV, Parquet, MinIO |

---

## Project Structure

```
coursework_one/
├── config/              # Configuration (PostgreSQL, MinIO)
├── modules/
│   ├── db/              # Database operations
│   ├── processing/      # Risk, scoring, signals
│   ├── storage/         # Export (local, MinIO)
│   └── ...
├── pipeline/            # 4-stage execution scripts
├── test/                # 494 unit & integration tests
├── static/              # Static assets
├── main.py              # Entry point
├── run_pipeline.py      # Orchestrator
├── pyproject.toml       # Dependencies
├── poetry.lock          # Locked versions
├── .flake8              # Linting config
├── .bandit.yaml         # Security config
├── pytest.ini           # Testing config
└── README.md            # This file
```

---

## Entry Point

**`main.py`** is the official user-facing entry point for running the pipeline. It is a clean wrapper that delegates to the underlying orchestration engine:

- **`main.py`**: Coursework-appropriate entry point (thin wrapper)
- **`run_pipeline.py`**: Core orchestration logic (4-stage pipeline controller)

Both accomplish the same goal and can be used interchangeably: `poetry run python3 main.py` or `poetry run python3 run_pipeline.py`. We recommend **`main.py`** for all commands.

---

## Code Quality

✅ **Tests**: 494 passed, 81% coverage (exceeds 80% min)
✅ **Linting**: Flake8 (0 violations)
✅ **Formatting**: Black & isort
✅ **Security**: Bandit scan

```bash
poetry run pytest -q              # Run tests
poetry run flake8                 # Check linting
poetry run black --check .        # Check formatting
```

---

## Key Features

- **Modular Design**: Independent, testable components
- **Risk-Aware**: VAR_95 and ATR_14 integrated throughout
- **Flexible Scheduling**: Daily/weekly/monthly execution
- **Multi-Format Storage**: CSV + Parquet + PostgreSQL + MinIO (optional)
- **Comprehensive Testing**: Unit, integration, and E2E tests
- **Professional Documentation**: Architecture, design, and deployment guides

---

## Configuration

**Optional MinIO Setup** (for cloud storage):
```bash
export MINIO_ENDPOINT="localhost:9000"
export MINIO_ACCESS_KEY="ift_bigdata"
export MINIO_SECRET_KEY="minio_password"
export MINIO_BUCKET="csreport"
export MINIO_SECURE="false"
```

Without MinIO: pipeline exports to local filesystem only (fully functional).

---

## Architecture & Documentation

For detailed technical documentation, see:
- **Architecture Report**: Main design document
- **Design Rationale**: Implementation decisions explained
- **Sphinx Docs** (`docs/`): API reference and installation guide

---

## Verification

After running the pipeline:
```bash
# Verify outputs
ls -lh analytics/processed/step{1,2,3}/

# Expected:
# - factors_latest.csv|parquet      (598 stocks)
# - selections_latest.csv|parquet   (110-130 selected)
# - signals_latest.csv|parquet      (signals)
```

---

**Team Luzin** | Coursework One | 2026
