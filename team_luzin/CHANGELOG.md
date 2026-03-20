# CHANGELOG

All notable submission-relevant changes for Team Luzin are documented in this file.

The authoritative changelog for submission is this team-level file.

## [2.1.0] - 2026-03-20 - Final Submission Structure and Documentation Alignment

### Changed
- Consolidated changelog tracking into the team root to match the coursework submission structure
- Updated Sphinx documentation to match the actual pipeline implementation and current file layout
- Corrected architecture, usage, troubleshooting, and FAQ references so they only mention modules and classes that exist in the submitted codebase
- Standardized math rendering in documentation for VAR, ATR, and composite score formulas

### Fixed
- Removed documentation inconsistencies around signal-generation classes and obsolete helper modules
- Fixed MinIO, selection-count, and pipeline-step descriptions to align with actual runtime behavior
- Fixed documentation build issues caused by mixed math syntax and stale references

### Verification
- `poetry run pytest -q` → 513 passed, 11 skipped
- Coverage: 80.20%
- `poetry run sphinx-build -b html docs docs/_build/html` succeeds

---

## [2.0.0] - 2026-03-16 - Coursework One Submission Readiness

### Added
- Code quality tooling: `.flake8`, `.bandit.yaml`, black, isort, flake8, bandit
- Comprehensive Sphinx documentation with architecture, installation, configuration, usage, troubleshooting, FAQ, and API reference
- Structured pipeline result models: `StepResult`, `PipelineRunSummary`, `ExportStatus`
- MinIO diagnostics and output readers for factor counts, selection counts, and signal counts
- Professionalized test suite structure with module-oriented test files

### Changed
- Refined the pipeline into a clear 4-step flow:
  - Step 1: VAR_95 and ATR_14 risk metrics
  - Step 2: sector-relative portfolio selection
  - Step 3: execution signal generation
  - Step 4: local + MinIO export
- Improved Step 4 export semantics so MinIO success, local-only success, MinIO failure, and disabled states are reported explicitly
- Updated README and docs to reflect the real pipeline entry points and outputs

### Fixed
- Removed hard-coded summary counts in pipeline reporting
- Fixed MinIO failure reporting and fallback behavior
- Fixed documentation and scoring inconsistencies across modules and pipeline descriptions
- Fixed code-quality issues including unused imports, unnecessary f-strings, and stale references

### Testing
- 500+ tests with unit, integration, and orchestration coverage
- Coverage maintained above the coursework minimum threshold of 80%

---

## [1.0.0] - 2026-02-28 - Coursework One Initial Delivery

### Added
- Core Coursework One pipeline implementation under `coursework_one/`
- PostgreSQL connectivity and company-universe loading
- yfinance-based price extraction and factor generation
- Risk metrics: VAR (95%) and ATR (14-period)
- Momentum, liquidity, trend, and composite scoring modules
- Signal generation and local/MinIO export pipeline
- CLI support for `--frequency`, `--run-date`, and `--dry-run`
- Centralized configuration via `config/conf.yaml`
- Automated tests and Poetry-based dependency management

### Infrastructure
- Docker Compose services for PostgreSQL and MinIO
- Local analytics outputs in CSV and Parquet formats
- Submitted team structure with `coursework_one/` and placeholder `coursework_two/`

---

## [Unreleased]

### Planned
- Coursework Two implementation
- Additional strategy and reporting enhancements as required by future coursework tasks

