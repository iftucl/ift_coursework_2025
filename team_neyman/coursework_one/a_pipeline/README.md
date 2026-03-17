# Team Neyman: Coursework One - Financial Data Pipeline
A modular, containerized ETL pipeline designed for high-performance quantitative financial analysis. This system synchronizes market data from yfinance and DoltHub, calculates both technical and fundamental factor signals, and implements a dual-storage strategy using PostgreSQL (Relational) and MinIO (Analytical Lake).

---

## 🏛️ Architecture Overview
The system follows a modern **Data Lakehouse** design:

* **Ingestion**: Extracts OHLCV data from yfinance and eps data from DoltHub.
* **Processing**: Cleansed the data and calculateed relevent factors.
* **Relational Storage (SQL)**: PostgreSQL handles rapid row-level updates and daily signal persistence.
* **Analytical Storage (Object)**: MinIO archives finalized reports in Apache Parquet format for optimized analytical performance.

## 🚀 Quick Start
### 1. Environment Setup
Ensure you have **Docker Desktop** and **Poetry** installed.

```powershell
# Install dependencies locally
poetry install

# Spin up the infrastructure
docker-compose up -d
```
### 2. Run the Pipeline
The main entry point handles the full end-to-end flow:

```powershell
docker exec -it worker_cw poetry run python main.py
```
## 🧪 Quality Assurance & Security
### Testing & Coverage
The project maintains high reliability with a suite of 46 unit and integration tests.

```powershell
# Run tests and generate HTML coverage report
poetry run pytest --cov=a_pipeline --cov-report html
```
Current Test Coverage: ~85% (Verified via pytest-cov)

### Code Quality (Linting)
We adhere to PEP 8 standards using a 3-tier formatting stack:

```powershell
poetry run isort a_pipeline
poetry run black a_pipeline
poetry run flake8 a_pipeline
```
### Security Auditing
The pipeline undergoes regular security scans to identify vulnerabilities in code and dependencies:

```powershell
poetry run bandit -r a_pipeline -lll
poetry run safety check
```
## 📚 Documentation
Technical documentation is generated using Sphinx. To view the full API reference and architectural deep-dive:

**PowerShell**
```powershell
start docs/_build/html/index.html
```
