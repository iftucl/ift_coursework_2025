Installation Guide
==================

Prerequisites
-------------

* Docker and Docker Compose
* Python 3.10 or higher
* `Poetry <https://python-poetry.org/>`_ (recommended) or pip
* Alpha Vantage API key (free tier, optional — Yahoo Finance is the default source)

1. Start Infrastructure
-----------------------

From the **repository root**, bring up the shared services:

.. code-block:: bash

   docker compose up --build postgres_db postgres_seed mongo_db \
       miniocw minio_client_cw pgadmin

Then start the Kafka overlay for Team Russell:

.. code-block:: bash

   docker compose -f docker-compose.yml \
       -f team_russell/coursework_one/docker-compose.kafka.yml \
       up --build zookeeper_russell kafka_russell

**Service ports:**

+-------------+---------------+------------------------------+
| Service     | External Port | Credentials                  |
+=============+===============+==============================+
| PostgreSQL  | 5439          | postgres / postgres          |
+-------------+---------------+------------------------------+
| MongoDB     | 27019         | (none)                       |
+-------------+---------------+------------------------------+
| MinIO API   | 9000          | ift_bigdata / minio_password |
+-------------+---------------+------------------------------+
| MinIO UI    | 9001          | ift_bigdata / minio_password |
+-------------+---------------+------------------------------+
| PgAdmin     | 5051          | admin@admin.com / root       |
+-------------+---------------+------------------------------+
| Kafka       | 9092          | (none)                       |
+-------------+---------------+------------------------------+

2. Apply Database Schema
------------------------

.. code-block:: bash

   docker exec -i postgres_db_cw psql -U postgres -d fift \
       -f /dev/stdin < team_russell/coursework_one/static/create_russell_tables.sql

Alternatively, connect via PgAdmin at http://localhost:5051.

3. Install Python Dependencies
------------------------------

.. code-block:: bash

   cd team_russell/coursework_one
   poetry install

Or with pip:

.. code-block:: bash

   pip install psycopg2-binary sqlalchemy "pymongo>=4.6" yfinance requests \
       "confluent-kafka>=2.4" minio pyyaml "pydantic>=2.0" "pandas>=2.2" \
       "numpy>=2.0" "scipy>=1.11" click
   pip install pytest pytest-cov

4. Configure API Keys
---------------------

Copy the example configuration and fill in your Alpha Vantage key:

.. code-block:: bash

   cp a_pipeline/config/conf.example.yaml a_pipeline/config/conf.yaml

Edit ``conf.yaml`` and set ``alpha_vantage.api_key``.  This is only required
when using ``--financial-source alphavantage``; Yahoo Finance is used by
default and requires no key.

Building the Documentation
--------------------------

From ``team_russell/coursework_one/``:

.. code-block:: bash

   pip install sphinx sphinx-rtd-theme
   sphinx-build -b html docs/ docs/_build/html

Open ``docs/_build/html/index.html`` in a browser to view the generated docs.
