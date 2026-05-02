# Coursework Two: Quantitative Investment Pipeline
UCL IFTE0003 Big Data in Quantitative Finance: *Team Neyman*

## Project Overview
The Team Neyman system is a modular **Quantitative Investment & ETL Pipeline** designed for automated factor-based trading, daily portfolio management, and historical backtesting. The project prioritizes environment parity, security auditing, and high test coverage to ensure reliable financial simulations.

## Architecture Overview
The system implements a modular ETL (Extract, Transform, Load) pipeline that leverages **Polyglot Persistence** to handle the varying needs of financial data.

**System Components**
- **Relational Layer (PostgreSQL):** Acts as the primary store for structured market data (OHLCV) and FX rates. It utilizes "UPSERT" logic to maintain data integrity.

- **Analytical Layer (MinIO & Parquet):** A high-performance "Data Lake" that persists daily portfolio snapshots in Apache Parquet format, reducing disk I/O for large-scale return analysis.

- **Document Layer (MongoDB):** Manages semi-structured metadata, trade logs, and pending orders, providing a schema-less audit trail of the investment worker's state.

**Data Flow Path**
1. **Extraction:** Raw data is synchronized from DoltHub repositories via the `dolt` CLI.

2. **Transformation:** Technical indicators are calculated and validated against strict null-rate thresholds.

3. **Persistence:** Validated prices are indexed in PostgreSQL, while execution logs are managed in MongoDB.

4. **Analytical Archive:** Final portfolio holdings and performance stats are serialized to Parquet and archived in the MinIO cluster.

## Installation & Setup
The project is containerized via Docker Compose to ensure 100% reproducibility across environments.

**Prerequisites**
- **Docker Desktop** (or Docker Engine on Linux)

- **Poetry** (for local dependency management)

- **Coursework One Setup**

**Quick Start (Docker)**
1. Launch Infrastructure:

```Bash
docker-compose up -d --build
```
2. Access Management Interfaces:

- PGAdmin: `http://localhost:5051` (admin@admin.com / root)

- MinIO Console: `http://localhost:9001` (ift_bigdata / minio_password)

- Postgres: `localhost:5439`

**Manual Execution**
To trigger the pipeline manually within the running worker container:

```Bash
docker exec -it investment_worker poetry run python main.py
```
## Usage & Development
For local development and native execution:

1. Install Dependencies:

```Bash
poetry install
```
2. Run the Backtest:

```Bash
poetry run python main.py --start 2024-01-01 --end 2025-01-01
```
**Quality Assurance**
To maintain the project’s high engineering standards, run the following quality suite:

- **Import Sorting:** poetry run isort .

- **Linting:** poetry run flake8 .

- **Security Audit:** poetry run bandit -r modules/

- **Dependency Audit:** poetry run safety scan

- **Unit Tests & Coverage:**

```Bash
poetry run pytest --cov=modules --cov-report=html
```
*Current total coverage: **>80%**.*

## Documentation
The project uses **Sphinx** with Google-style docstrings.

1. **Build HTML Docs:**

```Bash
cd docs
.\make.bat html
```
2. **View:** Open `docs/build/html/index.html` in your browser to access the Architecture Overview, API Reference, and Installation guides.

## Maintenance & Cleanup
The system provides surgical tools for environment management:

- `del_collection(name)`: Drops specific MongoDB strategy logs.

- `del_bucket(name)`: Recursively clears and removes MinIO analytical buckets.