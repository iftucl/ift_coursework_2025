# Changelog

All notable changes to the **Team Neyman Coursework** will be documented in this file.

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