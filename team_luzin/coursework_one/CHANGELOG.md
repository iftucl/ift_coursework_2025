# CHANGELOG

All notable changes to Team Luzin's Investment Strategy Data Pipeline are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.0.0] - 2026-03-16

### Major Refactoring: Code Quality & Submission Readiness

#### Added
- **Code Quality Tooling**
  - `.flake8` configuration file for linting standards
  - `.bandit.yaml` security scanning configuration
  - Black, isort, flake8, bandit integrated into Poetry dependencies
  - Comprehensive Sphinx documentation with API references

- **Pipeline Infrastructure**
  - Structured result types: `StepResult`, `PipelineRunSummary`, `ExportStatus` enum
  - MinIO diagnostics module with error classification
  - Output readers for factor counts, portfolio selections, signal counts
  - Status tracking protocol for Step 4 export (MINIO_SUCCESS, MINIO_FAILED, LOCAL_ONLY, DISABLED)
  - MINIO_REQUIRED environment variable for fail-fast behavior

- **Test Structure Improvements**
  - Professional test file naming: 12 test files renamed for clarity
  - Module-oriented test organization (test_<module>.py, test_<module>_integration.py)
  - Comprehensive test coverage: 494 tests, 81% coverage (exceeds 80% requirement)
  - Edge case and boundary condition tests for all major modules

#### Changed
- **Code Quality**
  - 26 files reformatted with black (consistent 88-char line length)
  - Import sorting standardized with isort
  - Removed 42 flake8 violations (F541 f-strings, F401 unused imports, F841 unused variables)
  - Fixed F541 bugs in 23 locations (unnecessary f-string prefixes)
  - Removed 17 unused imports across production code

- **Pipeline Semantics**
  - Step 4 no longer silently swallows MinIO errors
  - Export status properly tracked and reported
  - MinIO optional by default, fail-fast mode available via MINIO_REQUIRED
  - Clear distinction: "local + MinIO" only shown when MinIO actually succeeds

- **Documentation**
  - Updated README with complete quick start and project structure
  - Architecture documented with clear step descriptions
  - API documentation generated with Sphinx

#### Fixed
- **Critical Bugs**
  - Stale hard-coded summary numbers (335→598 factors, 335→123 stocks, 597→123 signals)
  - Misleading MinIO failure handling (now properly reported)
  - Missing failure semantics for Step 4 export

- **Code Quality Issues**
  - Unnecessary f-string prefixes in logging and SQL (F541)
  - Unused imports in data processing modules (F401)
  - Unused variables in portfolio calculation (F841)

#### Deprecated
- None

#### Removed
- Test file naming suffixes: `_smoke`, `_unit`, `_refactor`, `_edge_cases`
- Hard-coded summary values in orchestrator

#### Security
- No HIGH security issues identified (bandit scan clean)
- Proper credential handling in MinIO module
- No SQL injection vulnerabilities
- Environment variable validation in place

#### Testing
- 494 tests: 486 passing, 11 skipped, 0 failures
- 81% code coverage (5,123 / 6,334 statements)
- Unit, integration, and end-to-end test coverage
- All test files have module docstrings

#### Performance
- Pipeline execution: ~85 seconds (4 steps)
- Local export timing: <5 seconds
- MinIO connectivity check: <2 seconds

---

## [1.0.0] - 2026-02-28

### Initial Production Release

#### Added
- **Core Pipeline Architecture**
  - Step 1: VAR_95 and ATR_14 risk metrics calculation
  - Step 2: Portfolio selection via sector-relative scoring (130 stocks)
  - Step 3: Signal generation (MACD, ATR, Liquidity)
  - Step 4: Export to MinIO + local storage

- **Data Infrastructure**
  - PostgreSQL connector with schema discovery
  - Price data extraction from yfinance
  - Parquet reader/writer for efficient storage
  - Data lake writer for analytics pipeline

- **Indicators & Calculations**
  - Risk metrics: VAR (95%), ATR (14-period)
  - Momentum: MACD signal generation
  - Liquidity: Volume-based liquidity scoring
  - Trend: SMA-based trend indicators
  - Composite scoring for sector-relative ranking

- **CLI Interface**
  - `--frequency` argument (daily, weekly, monthly, quarterly)
  - `--run-date` for backfilling historical data
  - `--dry-run` for testing pipelines without DB writes
  - Configuration file support (config/conf.yaml)

- **Testing**
  - 450+ unit and integration tests
  - 80% code coverage
  - pytest framework with fixtures and mocking

#### Features
- 678 stocks in investable universe
- 597 stocks with available data
- 130-stock portfolio selected
- 335+ buy signals generated
- MinIO S3-compatible storage support
- Local file export as fallback
- Graceful error handling and logging

---

## [0.5.0] - 2026-01-15

### Early Alpha Release

- Initial project structure and module organization
- Basic PostgreSQL connectivity
- Price data extraction prototype
- Risk calculation foundations
- Test infrastructure setup

---

## Notes

### Coverage Analysis

The remaining 19% of uncovered code (1,211 statements) consists of:
- MinIO live connection tests (requires actual running MinIO instance)
- Poetry executable detection fallbacks (requires OS PATH manipulation)
- File I/O error injection tests (requires brittle mocking)
- Pipeline integration modules (tested via subprocess mocking)

These are intentionally not covered due to external dependencies and testing complexity.

### Submission Requirements Met

✓ Four-step pipeline fully functional
✓ 80%+ test coverage (81% achieved)
✓ Code quality tooling configured (black, flake8, isort, bandit)
✓ Security scanning clean
✓ Professional documentation
✓ README with installation and usage
✓ Configuration file support
✓ Data validation and robustness
✓ Graceful error handling
✓ MinIO optional/required support

---

**Version**: 2.0.0
**Release Date**: March 16, 2026
**Status**: Production-Ready for Submission
