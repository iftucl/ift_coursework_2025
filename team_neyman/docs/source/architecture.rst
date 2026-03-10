Architecture Overview
=====================
This system follows a modular ETL (Extract, Transform, Load) design:

1. **PostgreSQL Layer**: Handles data persistence.
2. **Factor Calculation**: Pandas logic for signals.
3. **Execution Layer**: The main entry point for daily runs.