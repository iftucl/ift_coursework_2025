Pipeline A — Data Ingestion
===========================

Pipeline A loads the investable universe from PostgreSQL, fetches daily
prices and annual financials from Yahoo Finance (or Alpha Vantage), publishes
raw payloads to Apache Kafka, and archives them in MinIO.

.. contents:: Modules
   :local:
   :depth: 1

----

modules.db_loader.company_loader
---------------------------------

Loads the investable universe from ``systematic_equity.company_static``.

.. py:class:: Company

   Immutable dataclass representing a single company in the universe.

   :param symbol: Ticker symbol (e.g. ``AAPL``).
   :type symbol: str
   :param gics_sector: GICS sector string (e.g. ``Information Technology``).
   :type gics_sector: str

.. py:function:: load_companies(engine) -> list[Company]

   Query ``systematic_equity.company_static`` and return all rows as
   :class:`Company` instances.

   :param engine: SQLAlchemy engine connected to the ``fift`` database.
   :type engine: sqlalchemy.engine.Engine
   :returns: List of :class:`Company` objects for every row in the table.
   :rtype: list[Company]

----

modules.fetcher.yfinance_fetcher
---------------------------------

Fetches daily closing prices and shares outstanding from Yahoo Finance.

.. py:function:: fetch_prices(symbol, start_date, end_date) -> dict | None

   Fetch daily OHLCV history and shares outstanding for a ticker.

   :param symbol: Ticker symbol (e.g. ``AAPL``).
   :type symbol: str
   :param start_date: Start date in ``YYYY-MM-DD`` format.
   :type start_date: str
   :param end_date: End date in ``YYYY-MM-DD`` format.
   :type end_date: str
   :returns: Dict with keys ``symbol``, ``prices`` (date → price),
             ``shares_outstanding``, ``fetched_at``; or ``None`` on failure.
   :rtype: dict | None

----

modules.fetcher.yfinance_financial_fetcher
-------------------------------------------

Fetches annual financial statements (balance sheet, income statement,
cash flow) from Yahoo Finance.

.. py:function:: fetch_balance_sheet(symbol) -> dict | None

   Extract annual balance sheet reports into standardised dicts.

   :param symbol: Ticker symbol.
   :type symbol: str
   :returns: Dict with ``symbol``, ``type``, ``data`` (list of annual
             reports), ``fetched_at``; or ``None`` on failure.
   :rtype: dict | None

.. py:function:: fetch_income_statement(symbol) -> dict | None

   Extract annual income statement and cash flow reports into standardised
   dicts.

   :param symbol: Ticker symbol.
   :type symbol: str
   :returns: Dict with ``symbol``, ``type``, ``data``, ``fetched_at``;
             or ``None`` on failure.
   :rtype: dict | None

----

modules.fetcher.alpha_vantage_fetcher
--------------------------------------

Fetches quarterly financial statements from the Alpha Vantage API.

Free tier limit: 25 requests / day. Each company requires 2 calls.
A 12-second rate-limit delay is applied between every request.

.. py:function:: fetch_balance_sheet(symbol, api_key) -> dict | None
   :no-index:

   Fetch quarterly balance sheet data for a symbol.

   :param symbol: Ticker symbol.
   :type symbol: str
   :param api_key: Alpha Vantage API key.
   :type api_key: str
   :returns: Dict with ``symbol``, ``type``, ``data``, ``fetched_at``;
             or ``None`` on rate-limit or HTTP error.
   :rtype: dict | None

.. py:function:: fetch_income_statement(symbol, api_key) -> dict | None
   :no-index:

   Fetch quarterly income statement data for a symbol.

   :param symbol: Ticker symbol.
   :type symbol: str
   :param api_key: Alpha Vantage API key.
   :type api_key: str
   :returns: Dict with ``symbol``, ``type``, ``data``, ``fetched_at``;
             or ``None`` on rate-limit or HTTP error.
   :rtype: dict | None

----

modules.kafka_producer.producer
---------------------------------

Wraps ``confluent_kafka.Producer`` for publishing raw data messages.

.. py:class:: RawDataProducer(bootstrap_servers, topic)

   Kafka producer that serialises payloads as JSON and uses the ticker
   symbol as the message key.

   :param bootstrap_servers: Kafka bootstrap server address (e.g.
                              ``localhost:9092``).
   :type bootstrap_servers: str
   :param topic: Kafka topic to publish to.
   :type topic: str

   .. py:method:: publish(symbol, payload)

      Publish a JSON payload to the configured Kafka topic.

      :param symbol: Ticker symbol used as the message key.
      :type symbol: str
      :param payload: Serialisable dict to publish.
      :type payload: dict

   .. py:method:: flush()

      Block until all outstanding messages are delivered.

----

modules.minio_writer.minio_writer
-----------------------------------

Archives raw JSON payloads in MinIO object storage.

.. py:class:: MinioRawWriter(endpoint, access_key, secret_key, bucket)

   Writes raw JSON files to MinIO at
   ``russell/<data_type>/<SYMBOL>_<YYYYMMDDHHMMSS>.json``.

   :param endpoint: MinIO endpoint (e.g. ``localhost:9000``).
   :type endpoint: str
   :param access_key: MinIO access key.
   :type access_key: str
   :param secret_key: MinIO secret key.
   :type secret_key: str
   :param bucket: Target bucket name (e.g. ``csreport``).
   :type bucket: str

   .. py:method:: write(symbol, data_type, payload)

      Serialise *payload* to JSON and upload it to MinIO.

      :param symbol: Ticker symbol (used in the object path).
      :type symbol: str
      :param data_type: One of ``prices``, ``balance_sheet``,
                        ``income_statement``.
      :type data_type: str
      :param payload: Dict to serialise and store.
      :type payload: dict
