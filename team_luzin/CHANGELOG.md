# Changelog

All notable changes to this project will be documented in this file.

## [2.0.0] - 2026-03-08 - Production-Ready Pipeline & GitHub Submission

### Major Changes
- **Clean Architecture**: Complete refactor for GitHub submission compliance
- **Testing**: Added pytest suite with 85%+ code coverage
- **Code Quality**: Integrated flake8, black, isort, and bandit
- **Documentation**: Full Sphinx documentation with API reference
- **Scheduling**: CLI arguments for daily/weekly/monthly execution
- **Security**: Vulnerability scanning and best practices

### Added
- **Comprehensive Test Suite**:
  - Unit tests for all modules
  - Integration tests for data pipeline
  - End-to-end tests with mock data
  - Coverage report: 85%+ of modules
  
- **Code Quality Tools**:
  - flake8 for linting
  - black for formatting
  - isort for import sorting
  - bandit for security scanning
  
- **Documentation**:
  - Full Sphinx documentation in docs/
  - API reference for all modules
  - Architecture overview
  - Installation and usage guides
  
- **CLI Arguments**:
  - run_pipeline.py now supports --frequency flag (daily/weekly/monthly)
  - run_date parameter for backfill capability
  - dry-run mode for testing
  
- **MinIO Enhancements**:
  - Ranked selections export (analytics/selections/)
  - Timestamped artifacts for audit trail
  - Both parquet and CSV exports
  
- **Module Docstrings**:
  - All functions, classes, and modules documented
  - Google-style docstrings for Sphinx compatibility

### Fixed
- Removed 36 debug/temporary files from codebase
- Fixed composite_rank to be sequential (1-335)
- Poetry dependency resolution in subprocess calls
- Null value handling in VaR calculations

### Changed
- Separated portfolio selection (Step 2) from execution signals (Step 3)
- 130 selections now exported to MinIO for audit trail
- Clean cache on every pipeline run
- Updated logging to be more informative

### Deployment
- Ready for GitHub submission
- PR template included
- No database changes committed
- Only team_luzin/ folder modified

---

## [1.0.0] - 2026-03-02 - Coursework One: Data Pipeline Infrastructure

### Added - Core Pipeline Components
- **run_complete_pipeline.py**: Unified orchestrator for complete data pipeline
  - Automatic calculation → selection → execution → MinIO upload workflow
  - Docker-based MinIO upload for reliable cloud storage
  - Comprehensive logging and error handling
  
- **calculate_all_factors.py**: Factor calculation engine
  - Momentum factors (6m, 12m) for 678 companies
  - Volatility calculations (6m, 12m)
  - Risk-adjusted momentum (RAM) as selection criterion
  - MACD technical indicators
  - 5-year historical data support
  
- **select_portfolio.py**: Quantitative portfolio selection
  - New strategy: Risk-Adjusted Momentum ranking (top 20% per GICS sector)
  - Liquidity filter: avg daily volume > $1,000,000
  - Separation of fundamental selection from technical execution
  - Results: 130 stocks from 678 universe
  
- **trading_execution.py**: MACD-based trading signal generation
  - Entry signals: MACD > Signal line (bullish)
  - Exit signals: MACD < Signal line (bearish)
  - Signal strength ranking: STRONG (histogram positive) vs WEAK
  - Results: 392 BUY (279 STRONG), 286 SELL (95 STRONG) signals

### Added - Data Infrastructure
- **Multi-format export support**:
  - CSV (158 KB): Universal compatibility
  - Parquet (96 KB, snappy compression): Analytics-optimized
  - JSONL (297 KB): Streaming-ready format
  
- **MinIO integration**:
  - Automatic upload to `csreport/pipeline_results/YYYYMMDD/`
  - Docker-based upload for network reliability
  - Organized data lake structure

- **PostgreSQL database**:
  - Schema: `systematic_equity`
  - Tables: `company_static` (678 companies), `momentum_factors` (calculated metrics)
  - Full historical data for 5+ years

### Added - Documentation
- **WORKFLOW_REPORT.md**: Complete pipeline documentation (700+ lines)
  - 6-phase architecture overview
  - Technical stack and infrastructure details
  - Data flow diagrams
  - Key metrics and KPIs
  - Error handling and QA procedures
  
- **PIPELINE_STRATEGY.md**: Implementation strategy guide
  - Detailed rationale for 2-filter selection approach
  - MACD usage for trading execution (not selection)
  - Workflow diagrams and execution checklists
  
- **AUTOMATED_PIPELINE.md**: Usage and scheduling guide
  - Single-command execution: `poetry run python run_complete_pipeline.py`
  - Cron scheduling for automated runs
  - Manual upload options
  - Troubleshooting guide
  
- **IMPLEMENTATION_SUMMARY.md**: Change documentation
  - Before/after comparison with old strategy
  - Test results and validation
  - Deployment checklist

### Added - Testing & Quality
- Unit tests for database connectors
- Integration tests for data pipeline
- Price extractor tests
- Comprehensive test coverage (80%+)

### Added - Configuration
- **config/conf.yaml**: Centralized configuration management
  - PostgreSQL connection details
  - MinIO endpoint and credentials
  - MongoDB configuration
  - Pipeline parameters (frequency, historical years)

### Changed - Strategy Refinement
- **Portfolio Selection Evolution**:
  - Old: 4-filter approach (momentum > 0 → MACD bullish → top 20% → volume)
  - New: 2-filter approach (RAM ranking top 20% per sector → volume)
  - Result: 130 stocks vs 73 (more opportunities, cleaner logic)
  - Benefit: Separation of concerns (selection vs execution)
  
- **MACD Usage**:
  - Removed from portfolio selection logic
  - Moved to trading execution phase (appropriate use case)
  - Used for timing, not portfolio composition

### Fixed
- Data quality issues in momentum_factors table
  - Filled missing volatility, momentum_score, risk_adjusted_momentum_6m columns
  - Verified all 678 records now have complete data
  - Implemented validation queries

### Deprecated
- Old multi-filter selection approach (superseded by RAM-based ranking)
- Direct MinIO uploads via Python (replaced with Docker-based for reliability)

### Infrastructure
- Docker Compose orchestration for PostgreSQL, MongoDB, MinIO
- GitHub Actions ready (for future CI/CD)
- Poetry-based dependency management
- Pytest framework for testing

### Performance Notes
- Factor Calculation: 10-20 minutes (678 stocks, 5 years)
- Portfolio Selection: 1-2 minutes
- Trading Execution: 1-2 minutes
- MinIO Upload: 10-30 seconds
- **Total pipeline time: ~15-25 minutes**

## [Unreleased]

### Planned
- Risk management rules implementation (position sizing, sector limits)
- Backtesting framework for signal validation
- Real-time monitoring dashboard
- Production deployment on cloud infrastructure

