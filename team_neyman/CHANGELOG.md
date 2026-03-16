# Changelog

All notable changes to the **Team Neyman Coursework** will be documented in this file.

## 2026-03-16
### Fixed
- Updated factors calculating logic to ensure alignment across multi-ticker datasets.
- Implemented a check on dolt pull output to skip database updates if no new data is found.

## 2026-03-15
### Added
- Integrated minio_loader.py to enable analytical data storage in Parquet format.
- Implemented wait_for_postgres() helper to ensure database readiness during container orchestration.

### Changed
- Migrated hardcoded credentials and parameters to a centralized config/conf.yaml architecture.
- Transitioned to a Docker-first deployment workflow, synchronizing services via docker-compose.

### Fixed
- Resolved Poetry hash mismatches and ModuleNotFoundError by enforcing in-container lock generation and adding PyYAML.
- Fixed data-loss bug in apply_filter by ensuring filtered DataFrames are explicitly returned to the main scope.


## 2026-03-14
### Added
- Achieved 80% total code coverage across the pipeline suite using pytest-cov.

### Changed
- Standardized all internal module references to use Absolute Imports for improved poetry compatibility.

### Fixed
- Resolved ValueError in calculate_adx by implementing .squeeze() to handle single-column DataFrame returns.


## 2026-03-13
### Changed
- Adjusted `main.py` logic to include arguments.


## 2026-03-10
### Added
- Integrated **APScheduler** for automated daily execution.
- Added **Docker** support with a multi-stage `Dockerfile` for containerized deployment.
- Implemented `argparse` CLI for flexible historical backfilling.

### Changed
- Migrated dependency management from `pip` to **Poetry**.
- Updated `postgres.py` functions to include Google Style docstrings for Sphinx compatibility.

### Fixed
- Resolved `ModuleNotFoundError` in Sphinx documentation by correcting `sys.path` in `conf.py`.
- Fixed duplicate primary key issues in `update_eps_estimate` using Pandas `drop_duplicates`.

### Security
- Resolved high-severity vulnerability in `pandas` identified by `safety check`.
- Verified SQL injection protection across all database modules using `bandit`.


## 2026-03-09
### Added
- Implemented companies filtering logic.

### Fixed
- Recreate `postgreSQL` database to include the right factors. 


## 2026-03-02
### Added
- Developed `postgreSQL` pipeline to store the price and factors data.

### Changed
- Clarify the factors calculation logic.


## 2026-03-01
### Added
- Established data fetching pipeline through `yfinance`.
- Added factor calculation funtions.