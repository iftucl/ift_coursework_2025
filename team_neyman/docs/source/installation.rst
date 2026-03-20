Installation & Setup
====================

The Team Neyman pipeline is designed to run within a containerized environment to ensure 100% reproducibility. This setup includes the PostgreSQL database, PGAdmin, and the Python execution worker.

Prerequisites
-------------
* **Docker Desktop** (or Docker Engine on Linux)
* **Docker Compose**

Quick Start (Docker)
--------------------
To launch the entire infrastructure and the data pipeline:

1. **Build and start the containers**:
   .. code-block:: bash

      docker-compose up -d

2. **Verify the services**:
   Once running, you can access the following interfaces:
   * **PGAdmin**: `http://localhost:5051` (Login: admin@admin.com / root)
   * **Postgres**: `localhost:5439`

Manual Execution via Docker
---------------------------
If you wish to trigger the pipeline manually while the containers are running:

.. code-block:: bash

   docker exec -it worker_cw poetry run python a_pipeline/main.py

Local Development (Non-Docker)
------------------------------
If you prefer to run the code natively on your host machine:

1. **Install Dependencies**:
   .. code-block:: bash

      cd coursework_one
      poetry install

2. **Dolt CLI**: Ensure the ``dolt`` binary is installed and available in your system PATH.

3. **Database**: Ensure a PostgreSQL instance is running and update ``config/conf.yaml`` with your local credentials.

4. **Run**:
   .. code-block:: bash

      poetry run python a_pipeline/main.py