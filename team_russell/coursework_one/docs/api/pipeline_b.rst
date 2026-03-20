Pipeline B — Processing and Storage
=====================================

Pipeline B is a long-lived Kafka consumer that transforms raw messages and
writes structured records to MongoDB (raw audit store) and PostgreSQL
(structured query store).

.. contents:: Modules
   :local:
   :depth: 1

----

modules.kafka_consumer.consumer
---------------------------------

Wraps ``confluent_kafka.Consumer`` for reliable message consumption.

.. py:class:: RawDataConsumer(bootstrap_servers, topics, group_id)

   Kafka consumer with graceful shutdown and partition-EOF handling.

   :param bootstrap_servers: Kafka bootstrap server address.
   :type bootstrap_servers: str
   :param topics: List of topic names to subscribe to.
   :type topics: list[str]
   :param group_id: Consumer group ID (default: ``russell_b_pipeline``).
   :type group_id: str

   .. py:method:: consume(on_message)

      Poll Kafka indefinitely, calling *on_message* for each valid message.

      Handles ``PARTITION_EOF`` and ``UNKNOWN_TOPIC_OR_PART`` errors
      gracefully without raising. Stops when ``_running`` is ``False``.

      :param on_message: Callable invoked with the deserialised message dict.
      :type on_message: Callable[[dict], None]

   .. py:method:: close()

      Commit offsets and close the Kafka consumer connection.

----

modules.transformer.transformer
---------------------------------

Transforms raw API payloads into structured records for database storage.

.. py:function:: transform_prices(raw) -> list[dict]

   Flatten a raw yfinance price dict into a list of daily price records.

   :param raw: Dict with keys ``symbol``, ``prices`` (date → price),
               ``shares_outstanding``.
   :type raw: dict
   :returns: List of dicts each with ``symbol``, ``price_date``,
             ``closing_price``, ``shares_outstanding``.
   :rtype: list[dict]

.. py:function:: transform_financials(balance_sheet, income_statement) -> list[dict]

   Align annual balance sheet and income statement data by fiscal date.

   Only dates present in **both** sources are included. Book value is
   derived as ``total_assets - total_liabilities``.

   :param balance_sheet: Raw dict from the balance sheet fetcher.
   :type balance_sheet: dict
   :param income_statement: Raw dict from the income statement fetcher.
   :type income_statement: dict
   :returns: List of dicts with standardised financial fields per fiscal year.
   :rtype: list[dict]

----

modules.db_writer.mongo_writer
--------------------------------

Persists raw records to MongoDB as an audit and replay store.

.. py:class:: MongoRawWriter(uri, database)

   Upserts documents into MongoDB collections keyed by symbol.

   :param uri: MongoDB connection URI (e.g. ``mongodb://localhost:27019``).
   :type uri: str
   :param database: Database name (e.g. ``investment_data``).
   :type database: str

   Collections used: ``raw_prices``, ``raw_balance_sheet``,
   ``raw_income_statement``.

   .. py:method:: write_prices(symbol, records)

      Upsert price records for *symbol* into ``raw_prices``.

      :param symbol: Ticker symbol.
      :type symbol: str
      :param records: List of price record dicts.
      :type records: list[dict]

   .. py:method:: write_financials(symbol, records)

      Upsert financial records for *symbol* into the appropriate collection.

      :param symbol: Ticker symbol.
      :type symbol: str
      :param records: List of financial record dicts.
      :type records: list[dict]

----

modules.db_writer.postgres_writer
-----------------------------------

Persists structured records to PostgreSQL via SQLAlchemy upserts.

.. py:class:: PostgresWriter(engine)

   Writes to ``systematic_equity`` schema tables using
   ``INSERT … ON CONFLICT DO UPDATE`` for idempotency.

   :param engine: SQLAlchemy engine connected to the ``fift`` database.
   :type engine: sqlalchemy.engine.Engine

   .. py:method:: write_prices(symbol, records)

      Upsert daily price records into ``systematic_equity.price_history``.

      :param symbol: Ticker symbol.
      :type symbol: str
      :param records: List of price record dicts.
      :type records: list[dict]

   .. py:method:: write_financials(symbol, records)

      Upsert annual financial records into ``systematic_equity.financials``.

      :param symbol: Ticker symbol.
      :type symbol: str
      :param records: List of financial record dicts.
      :type records: list[dict]
