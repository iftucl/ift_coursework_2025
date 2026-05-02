Installation & Setup
====================

The Team Neyman pipeline is designed to run within a containerized environment to ensure 100% reproducibility across development and production environments.

Prerequisites
-------------
* **Docker Desktop** (or Docker Engine on Linux)
* **Docker Compose**
* **Poetry** (for local development)

Quick Start (Docker)
--------------------
To launch the entire infrastructure (Postgres, Mongo, MinIO, and the Worker):

1. **Build and start the containers**:
   .. code-block:: bash

      docker-compose up -d

2. **Verify the services**:
   Once running, you can access the following management interfaces:
   * **PGAdmin**: `http://localhost:5051` (Login: admin@admin.com / root)
   * **MinIO Console**: `http://localhost:9001` (Login: ift_bigdata / minio_password)
   * **Postgres**: `localhost:5439`

Manual Execution via Docker
---------------------------
If you wish to trigger a specific rebalance or backtest manually while the containers are running:

.. code-block:: bash

   docker exec -it investment_worker poetry run python main.py

Local Development (Native)
------------------------------
If you prefer to run the code natively on your host machine:

1. **Install Dependencies**:
   .. code-block:: bash

      cd coursework_one
      poetry install

2. **Environment Check**:
   * Ensure the ``dolt`` binary is installed in your system PATH.
   * Update ``config/conf.yaml`` to point to your local database instances.

3. **Run**:
   .. code-block:: bash

      poetry run python main.py