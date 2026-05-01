"""Unit tests for Pipeline A Kafka producer module."""

import json
import logging
from unittest.mock import MagicMock, patch

from modules.kafka_producer.producer import RawDataProducer


class TestRawDataProducer:
    @patch("modules.kafka_producer.producer.Producer")
    def test_publish_calls_produce_with_correct_topic(self, mock_producer_cls):
        mock_producer = MagicMock()
        mock_producer_cls.return_value = mock_producer

        producer = RawDataProducer("localhost:9092")
        producer.publish("my_topic", "AAPL", {"price": 150.0})

        args = mock_producer.produce.call_args[0]
        assert args[0] == "my_topic"

    @patch("modules.kafka_producer.producer.Producer")
    def test_publish_uses_symbol_as_key(self, mock_producer_cls):
        mock_producer = MagicMock()
        mock_producer_cls.return_value = mock_producer

        producer = RawDataProducer("localhost:9092")
        producer.publish("topic", "AAPL", {"price": 150.0})

        kwargs = mock_producer.produce.call_args[1]
        assert kwargs["key"] == b"AAPL"

    @patch("modules.kafka_producer.producer.Producer")
    def test_publish_serialises_data_as_json(self, mock_producer_cls):
        mock_producer = MagicMock()
        mock_producer_cls.return_value = mock_producer

        data = {"symbol": "AAPL", "price": 150.0}
        producer = RawDataProducer("localhost:9092")
        producer.publish("topic", "AAPL", data)

        kwargs = mock_producer.produce.call_args[1]
        decoded = json.loads(kwargs["value"].decode("utf-8"))
        assert decoded == data

    @patch("modules.kafka_producer.producer.Producer")
    def test_publish_polls_after_produce(self, mock_producer_cls):
        mock_producer = MagicMock()
        mock_producer_cls.return_value = mock_producer

        producer = RawDataProducer("localhost:9092")
        producer.publish("topic", "AAPL", {})

        mock_producer.poll.assert_called_once_with(0)

    @patch("modules.kafka_producer.producer.Producer")
    def test_flush_delegates_to_underlying_producer(self, mock_producer_cls):
        mock_producer = MagicMock()
        mock_producer_cls.return_value = mock_producer

        producer = RawDataProducer("localhost:9092")
        producer.flush()

        mock_producer.flush.assert_called_once()

    @patch("modules.kafka_producer.producer.Producer")
    def test_delivery_report_logs_error_on_failure(self, mock_producer_cls, caplog):
        mock_producer_cls.return_value = MagicMock()
        with caplog.at_level(logging.ERROR, logger="modules.kafka_producer.producer"):
            RawDataProducer._delivery_report("some error", None)
        assert "delivery failed" in caplog.text.lower()

    @patch("modules.kafka_producer.producer.Producer")
    def test_delivery_report_no_error_logged_on_success(self, mock_producer_cls, caplog):
        mock_producer_cls.return_value = MagicMock()
        mock_msg = MagicMock()
        mock_msg.topic.return_value = "topic"
        mock_msg.partition.return_value = 0
        with caplog.at_level(logging.ERROR, logger="modules.kafka_producer.producer"):
            RawDataProducer._delivery_report(None, mock_msg)
        assert "delivery failed" not in caplog.text.lower()
