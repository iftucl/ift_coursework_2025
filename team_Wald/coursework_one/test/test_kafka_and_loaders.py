"""
Tests for Kafka event handler, MinIO uploader, and MongoDB loader modules.
"""

from unittest.mock import MagicMock, patch

import pandas as pd


class TestEventProducer:
    """Tests for Kafka EventProducer."""

    def test_init_default_bootstrap(self):
        with patch.dict("os.environ", {"KAFKA_BOOTSTRAP_SERVERS": "test:9092"}):
            from modules.kafka.kafka_handler import EventProducer

            producer = EventProducer()
            assert producer.bootstrap_servers == "test:9092"

    def test_init_custom_bootstrap(self):
        from modules.kafka.kafka_handler import EventProducer

        producer = EventProducer(bootstrap_servers="custom:9092")
        assert producer.bootstrap_servers == "custom:9092"

    def test_publish_without_connection(self):
        from modules.kafka.kafka_handler import EventProducer

        producer = EventProducer()
        producer._producer = None
        # Should not raise — degrades gracefully
        producer.publish_event("test-topic", "key", {"data": "value"})

    def test_publish_batch_empty(self):
        from modules.kafka.kafka_handler import EventProducer

        producer = EventProducer()
        producer._producer = None
        producer.publish_batch("test-topic", [])

    def test_close_without_connection(self):
        from modules.kafka.kafka_handler import EventProducer

        producer = EventProducer()
        producer._producer = None
        producer.close()

    def test_publish_batch_with_key_field(self):
        from modules.kafka.kafka_handler import EventProducer

        producer = EventProducer()
        mock_prod = MagicMock()
        producer._producer = mock_prod
        events = [{"company_id": "AAPL", "data": 1}, {"company_id": "MSFT", "data": 2}]
        producer.publish_batch("test-topic", events, key_field="company_id")
        assert mock_prod.send.call_count == 2

    def test_flush(self):
        from modules.kafka.kafka_handler import EventProducer

        producer = EventProducer()
        producer._producer = MagicMock()
        producer.flush()
        producer._producer.flush.assert_called_once()

    def test_flush_without_connection(self):
        """Test flush is safe when producer is not connected."""
        from modules.kafka.kafka_handler import EventProducer

        producer = EventProducer()
        producer._producer = None
        producer.flush()  # Should not raise

    def test_close_with_active_producer(self):
        """Test close flushes and closes an active producer."""
        from modules.kafka.kafka_handler import EventProducer

        producer = EventProducer()
        mock_prod = MagicMock()
        producer._producer = mock_prod
        producer.close()
        mock_prod.flush.assert_called_once()
        mock_prod.close.assert_called_once()
        assert producer._producer is None

    @patch("modules.kafka.kafka_handler.KAFKA_AVAILABLE", False)
    def test_producer_property_kafka_unavailable(self):
        """Test producer property returns None when kafka is not installed."""
        from modules.kafka.kafka_handler import EventProducer

        producer = EventProducer()
        assert producer.producer is None

    @patch("modules.kafka.kafka_handler.KAFKA_AVAILABLE", True)
    @patch("modules.kafka.kafka_handler.KafkaProducer")
    def test_producer_property_success(self, mock_kafka_producer_cls):
        """Test producer property successfully initializes."""
        from modules.kafka.kafka_handler import EventProducer

        mock_instance = MagicMock()
        mock_kafka_producer_cls.return_value = mock_instance
        producer = EventProducer(bootstrap_servers="test:9092")
        result = producer.producer
        assert result is mock_instance

    @patch("modules.kafka.kafka_handler.KAFKA_AVAILABLE", True)
    @patch("modules.kafka.kafka_handler.KafkaProducer")
    def test_producer_property_connection_failure(self, mock_kafka_producer_cls):
        """Test producer property handles connection failure."""
        from modules.kafka.kafka_handler import EventProducer

        mock_kafka_producer_cls.side_effect = Exception("Connection refused")
        producer = EventProducer()
        result = producer.producer
        assert result is None

    def test_publish_event_success(self):
        """Test successful event publishing."""
        from modules.kafka.kafka_handler import EventProducer

        producer = EventProducer()
        mock_prod = MagicMock()
        producer._producer = mock_prod
        producer.publish_event("test-topic", "AAPL", {"data": "value"})
        mock_prod.send.assert_called_once_with("test-topic", key="AAPL", value={"data": "value"})

    def test_publish_event_exception(self):
        """Test publish_event handles send exceptions gracefully."""
        from modules.kafka.kafka_handler import EventProducer

        producer = EventProducer()
        mock_prod = MagicMock()
        mock_prod.send.side_effect = Exception("Send failed")
        producer._producer = mock_prod
        # Should not raise
        producer.publish_event("test-topic", "AAPL", {"data": "value"})


class TestEventConsumer:
    """Tests for Kafka EventConsumer."""

    def test_init_defaults(self):
        from modules.kafka.kafka_handler import EventConsumer

        consumer = EventConsumer()
        assert consumer.group_id == "cw1-sentiment-consumer"

    def test_init_custom_topics(self):
        from modules.kafka.kafka_handler import EventConsumer

        consumer = EventConsumer(topics=["custom.topic"])
        assert "custom.topic" in consumer.topics

    def test_close_without_connection(self):
        from modules.kafka.kafka_handler import EventConsumer

        consumer = EventConsumer()
        consumer._consumer = None
        consumer.close()

    def test_close_with_connection(self):
        """Test close properly closes an active consumer."""
        from modules.kafka.kafka_handler import EventConsumer

        consumer = EventConsumer()
        mock_consumer = MagicMock()
        consumer._consumer = mock_consumer
        consumer.close()
        mock_consumer.close.assert_called_once()
        assert consumer._consumer is None

    @patch("modules.kafka.kafka_handler.KAFKA_AVAILABLE", False)
    def test_consumer_property_kafka_unavailable(self):
        """Test consumer property returns None when kafka is not installed."""
        from modules.kafka.kafka_handler import EventConsumer

        consumer = EventConsumer()
        assert consumer.consumer is None

    @patch("modules.kafka.kafka_handler.KAFKA_AVAILABLE", True)
    @patch("modules.kafka.kafka_handler.KafkaConsumer")
    def test_consumer_property_success(self, mock_kafka_consumer_cls):
        """Test consumer property successfully initializes."""
        from modules.kafka.kafka_handler import EventConsumer

        mock_instance = MagicMock()
        mock_kafka_consumer_cls.return_value = mock_instance
        consumer = EventConsumer(topics=["test-topic"])
        result = consumer.consumer
        assert result is mock_instance

    @patch("modules.kafka.kafka_handler.KAFKA_AVAILABLE", True)
    @patch("modules.kafka.kafka_handler.KafkaConsumer")
    def test_consumer_property_failure(self, mock_kafka_consumer_cls):
        """Test consumer property handles initialization failure."""
        from modules.kafka.kafka_handler import EventConsumer

        mock_kafka_consumer_cls.side_effect = Exception("Connection refused")
        consumer = EventConsumer(topics=["test-topic"])
        result = consumer.consumer
        assert result is None

    def test_consume_with_no_consumer(self):
        """Test consume returns early when consumer is None."""
        from modules.kafka.kafka_handler import EventConsumer

        consumer = EventConsumer()
        consumer._consumer = None
        with patch.object(type(consumer), "consumer", new_callable=lambda: property(lambda self: None)):
            callback = MagicMock()
            consumer.consume(callback)
            callback.assert_not_called()

    def test_consume_processes_messages(self):
        """Test consume correctly processes messages via callback."""
        from modules.kafka.kafka_handler import EventConsumer

        consumer = EventConsumer()
        mock_consumer = MagicMock()

        # Create mock topic partition and messages
        mock_tp = MagicMock()
        mock_tp.topic = "news-articles"
        mock_msg1 = MagicMock()
        mock_msg1.value = {"headline": "Article 1", "company_id": "AAPL"}
        mock_msg2 = MagicMock()
        mock_msg2.value = {"headline": "Article 2", "company_id": "MSFT"}

        mock_consumer.poll.return_value = {mock_tp: [mock_msg1, mock_msg2]}
        consumer._consumer = mock_consumer

        callback = MagicMock()
        consumer.consume(callback, max_messages=10, timeout_ms=500)
        assert callback.call_count == 2
        callback.assert_any_call("news-articles", {"headline": "Article 1", "company_id": "AAPL"})
        callback.assert_any_call("news-articles", {"headline": "Article 2", "company_id": "MSFT"})

    def test_consume_handles_callback_exception(self):
        """Test consume handles exceptions in the callback gracefully."""
        from modules.kafka.kafka_handler import EventConsumer

        consumer = EventConsumer()
        mock_consumer = MagicMock()

        mock_tp = MagicMock()
        mock_tp.topic = "test-topic"
        mock_msg = MagicMock()
        mock_msg.value = {"data": "test"}
        mock_consumer.poll.return_value = {mock_tp: [mock_msg]}
        consumer._consumer = mock_consumer

        callback = MagicMock(side_effect=Exception("Callback error"))
        # Should not raise
        consumer.consume(callback)

    def test_consume_empty_poll(self):
        """Test consume with empty poll result."""
        from modules.kafka.kafka_handler import EventConsumer

        consumer = EventConsumer()
        mock_consumer = MagicMock()
        mock_consumer.poll.return_value = {}
        consumer._consumer = mock_consumer

        callback = MagicMock()
        consumer.consume(callback)
        callback.assert_not_called()

    def test_consume_multiple_topics(self):
        """Test consume processes messages from multiple topic partitions."""
        from modules.kafka.kafka_handler import EventConsumer

        consumer = EventConsumer()
        mock_consumer = MagicMock()

        mock_tp1 = MagicMock()
        mock_tp1.topic = "news-articles"
        mock_tp2 = MagicMock()
        mock_tp2.topic = "value-metrics"
        mock_msg1 = MagicMock()
        mock_msg1.value = {"topic": "news"}
        mock_msg2 = MagicMock()
        mock_msg2.value = {"topic": "metrics"}

        mock_consumer.poll.return_value = {mock_tp1: [mock_msg1], mock_tp2: [mock_msg2]}
        consumer._consumer = mock_consumer

        callback = MagicMock()
        consumer.consume(callback)
        assert callback.call_count == 2


class TestGetEventProducer:
    """Tests for get_event_producer factory."""

    def test_factory_with_config(self):
        from modules.kafka.kafka_handler import get_event_producer

        cfg = {"BootstrapServers": "config:9092"}
        producer = get_event_producer(cfg)
        assert producer.bootstrap_servers == "config:9092"

    def test_factory_without_config(self):
        from modules.kafka.kafka_handler import get_event_producer

        producer = get_event_producer(None)
        assert producer is not None


class TestMinioUploader:
    """Tests for MinIO upload functions."""

    def test_upload_price_data(self):
        from modules.loading.minio_uploader import upload_price_data

        mock_minio = MagicMock()
        df = pd.DataFrame({"Close": [150.0]}, index=pd.to_datetime(["2024-01-01"]))
        upload_price_data(mock_minio, "AAPL", df, "2024")
        mock_minio.upload_csv.assert_called_once()

    def test_upload_price_data_empty(self):
        from modules.loading.minio_uploader import upload_price_data

        mock_minio = MagicMock()
        upload_price_data(mock_minio, "AAPL", pd.DataFrame(), "2024")
        mock_minio.upload_csv.assert_not_called()

    def test_upload_financial_data(self):
        from modules.loading.minio_uploader import upload_financial_data

        mock_minio = MagicMock()
        data = {"income_statement": {"field": "value"}}
        upload_financial_data(mock_minio, "AAPL", data, "2024")
        mock_minio.upload_json.assert_called()

    def test_upload_financial_data_empty(self):
        from modules.loading.minio_uploader import upload_financial_data

        mock_minio = MagicMock()
        upload_financial_data(mock_minio, "AAPL", {}, "2024")
        mock_minio.upload_json.assert_not_called()

    def test_upload_news_articles(self):
        from modules.loading.minio_uploader import upload_news_articles

        mock_minio = MagicMock()
        articles = [{"headline": "test", "company_id": "AAPL"}]
        upload_news_articles(mock_minio, "AAPL", articles, "2024-01-01")
        mock_minio.upload_json.assert_called_once()

    def test_upload_news_articles_empty(self):
        from modules.loading.minio_uploader import upload_news_articles

        mock_minio = MagicMock()
        upload_news_articles(mock_minio, "AAPL", [], "2024-01-01")
        mock_minio.upload_json.assert_not_called()

    def test_upload_company_info(self):
        from modules.loading.minio_uploader import upload_company_info

        mock_minio = MagicMock()
        info = {"symbol": "AAPL", "pe_ratio": 28.5}
        upload_company_info(mock_minio, "AAPL", info)
        mock_minio.upload_json.assert_called_once()


class TestMongoLoader:
    """Tests for MongoDB loader functions."""

    def test_store_news_articles(self, mock_mongo_client):
        from modules.loading.mongo_loader import store_news_articles

        articles = [
            {"headline": "Test 1", "company_id": "AAPL"},
            {"headline": "Test 2", "company_id": "MSFT"},
        ]
        mock_mongo_client.insert_documents = MagicMock(return_value=2)
        count = store_news_articles(mock_mongo_client, articles)
        assert count == 2

    def test_store_news_articles_empty(self, mock_mongo_client):
        from modules.loading.mongo_loader import store_news_articles

        mock_mongo_client.insert_documents = MagicMock(return_value=0)
        count = store_news_articles(mock_mongo_client, [])
        assert count == 0

    def test_store_articles_for_company(self, mock_mongo_client):
        from modules.loading.mongo_loader import store_articles_for_company

        articles = [{"headline": "Test"}]
        mock_mongo_client.insert_documents = MagicMock(return_value=1)
        count = store_articles_for_company(mock_mongo_client, "AAPL", "Apple Inc", articles)
        assert count == 1

    def test_get_company_articles(self, mock_mongo_client):
        from modules.loading.mongo_loader import get_company_articles

        mock_mongo_client.query_documents = MagicMock(return_value=[{"headline": "Test"}])
        result = get_company_articles(mock_mongo_client, "AAPL")
        assert len(result) == 1

    def test_get_articles_by_date_range(self, mock_mongo_client):
        from modules.loading.mongo_loader import get_articles_by_date_range

        mock_mongo_client.query_documents = MagicMock(return_value=[])
        result = get_articles_by_date_range(mock_mongo_client, "AAPL", "2024-01-01", "2024-12-31")
        assert isinstance(result, list)


class TestFxExtractor:
    """Tests for FX rate extraction."""

    @patch("modules.extraction.fx_extractor.yf")
    def test_fetch_fx_rates_success(self, mock_yf):
        from modules.extraction.fx_extractor import fetch_fx_rates

        idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
        mock_df = pd.DataFrame(
            {"Open": [1.27, 1.28], "High": [1.28, 1.29], "Low": [1.26, 1.27], "Close": [1.27, 1.28]},
            index=idx,
        )
        mock_yf.download.return_value = mock_df
        result = fetch_fx_rates("2024-01-01", "2024-12-31", pairs=["GBPUSD=X"])
        assert "GBPUSD=X" in result

    @patch("modules.extraction.fx_extractor.yf")
    def test_fetch_fx_rates_empty(self, mock_yf):
        from modules.extraction.fx_extractor import fetch_fx_rates

        mock_yf.download.return_value = pd.DataFrame()
        result = fetch_fx_rates("2024-01-01", "2024-12-31", pairs=["GBPUSD=X"])
        assert "GBPUSD=X" in result
