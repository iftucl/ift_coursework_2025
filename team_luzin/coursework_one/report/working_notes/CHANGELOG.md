# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-03-08

### Added

#### Project Structure
- Reorganized modules into clean architecture: `input/`, `processing/`, `signals/`, `output/`
- Created `Main.py` as primary entry point alongside `run_pipeline.py`
- Added `static/example_outputs/` for sample data and documentation
- Implemented proper module hierarchy with `__init__.py` files

#### CLI Arguments
- Added `--frequency` option: daily, weekly, monthly, quarterly
- Added `--run-date` for explicit date-based execution
- Added `--dry-run` for test execution without database writes
- Comprehensive help and examples via `-h/--help`

#### New Module Wrappers
- `modules/input/market_data_loader.py` - Unified market data interface
- `modules/output/export_analytics.py` - Standardized export utilities
- `modules/signals/execution_signals.py` - Signal generation orchestration

#### Documentation
- Created comprehensive Sphinx documentation in `docs/`
- Added `docs/quickstart.rst` with getting started guide
- Added `docs/architecture.rst` explaining pipeline design
- Added `docs/testing.rst` with test running instructions
- Added `docs/code_quality.rst` with linting/formatting guide
- Added `docs/deployment.rst` with production setup guide
- Added `pytest.ini` with test configuration and coverage targets
- Updated README.md with complete project structure diagram

#### Testing & Quality
- Comprehensive pytest.ini configuration (80%+ coverage target)
- Added code quality tool integration:
  - flake8 for linting
  - black for formatting
  - isort for import sorting
  - bandit for security scanning
- Created `.gitignore` with comprehensive exclusions

#### Configuration
- Added `.coveragerc` for coverage reporting
- Configured pyproject.toml with all dev dependencies
- Added Sphinx documentation setup with RTD theme

### Changed

#### Dependencies
- Updated pyproject.toml version from 0.1.0 to 2.0.0
- Added comprehensive dev dependencies (pytest, black, flake8, etc.)
- Added documentation dependencies (sphinx, sphinx-rtd-theme)

#### Pipeline
- Enhanced `run_pipeline.py` with argparse-based CLI
- Added execution planning and dry-run validation
- Improved logging for scheduling visibility

#### README
- Expanded from 269 to 500+ lines with comprehensive documentation
- Added project structure visualization
- Added pipeline architecture details with metrics table
- Added troubleshooting section
- Added development workflow section
- Added security practices section

### Fixed

- Organized modules to reduce circular dependencies
- Standardized error handling in new module wrappers
- Improved logging configuration across modules

### Removed

- Legacy configuration patterns (now centralized in conf.yaml)
- Redundant copy of pipeline documentation

## [1.0.0] - 2026-03-01

### Initial Release

#### Pipeline Implementation
- Step 1: VAR_95 & ATR_14 calculation (597/678 success rate)
- Step 2: Portfolio selection (130 stocks via composite scoring)
- Step 3: Execution signal generation (335 BUY signals)
- Step 4: MinIO export with Parquet & CSV formats

#### Features
- PostgreSQL integration for momentum_factors table
- MinIO datalake export (portfolio, signals, selections)
- Ranked selections export (1-130 ranking)
- Config-driven execution with YAML configuration
- Comprehensive logging with file and console output
- Modular architecture supporting independent data processors

#### Documentation
- Initial README with quick start guide
- Pipeline architecture documentation
- Data flow diagrams and examples
- Dependencies listed in pyproject.toml

### Architecture

```
Input (678 stocks)
  ↓
Step 1: Risk Metrics [VAR_95, ATR_14]
  ├─ Success: 597 stocks (88.1%)
  ├─ Time: ~1:47
  ↓
Step 2: Portfolio Selection [Composite Score]
  ├─ Selected: 130 stocks
  ├─ Metrics: RAM, Liquidity, VaR
  ├─ Time: ~0.25s
  ↓
Step 3: Execution Signals [MACD, ATR, Liquidity]
  ├─ BUY Signals: 335 stocks
  ├─ Time: ~0.15s
  ↓
Step 4: MinIO Export
  ├─ Parquet & CSV formats
  ├─ Bucket: csreport
  ├─ Time: ~0.10s
  ↓
Output Files + MinIO
```

### Key Metrics

- **Input Universe**: 678 stocks (S&P 500 + Russell 1000)
- **Data Availability**: 88.1% (597 successful)
- **Portfolio Size**: 130 stocks
- **Execution Signals**: 335 BUY signals
- **Pipeline Runtime**: ~2 minutes total
- **Database**: PostgreSQL (systematic_equity schema)
- **Data Lake**: MinIO (csreport bucket)

---

## Submission Readiness Checklist

### ✅ Code Quality
- [x] flake8 linting configured
- [x] black formatting configured
- [x] isort import sorting configured
- [x] bandit security scanning configured

### ✅ Testing
- [x] pytest configured (80%+ coverage target)
- [x] 13+ test files present
- [x] Unit and integration tests included
- [x] pytest.ini with coverage reporting

### ✅ Documentation
- [x] README.md comprehensive (500+ lines)
- [x] Sphinx documentation setup
- [x] Docstrings in all modules
- [x] Architecture documentation
- [x] Quick start guide
- [x] Troubleshooting section

### ✅ Code Organization
- [x] Modular structure (input/processing/signals/output)
- [x] Configuration-driven design
- [x] Proper error handling
- [x] Logging throughout

### ✅ Submission Requirements
- [x] CLI arguments for scheduling flexibility
- [x] Frequency support: daily/weekly/monthly/quarterly
- [x] Dry-run mode for testing
- [x] .gitignore for credentials and artifacts
- [x] pyproject.toml with all dependencies
- [x] CHANGELOG.md documenting all changes

### 🔄 Ready for GitHub PR to @uceslc0

See [README.md](README.md) for full documentation and [docs/](docs/) for Sphinx HTML documentation.
