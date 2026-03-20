"""Unit tests for Pipeline B Kafka consumer module."""

import json
from unittest.mock import MagicMock, patch

from confluent_kafka import KafkaError
from modules.kafka_consumer.consumer import RawDataConsumer


def _make_msg(payload: dict):
    """Build a mock Kafka message carrying a JSON payload."""
    msg = MagicMock()
    msg.error.return_value = None
    msg.value.return_value = json.dumps(payload).encode("utf-8")
    return msg


def _make_error_msg(code):
    """Build a mock Kafka message with a given error code."""
    msg = MagicMock()
    err = MagicMock()
    err.code.return_value = code
    msg.error.return_value = err
    return msg


def _consume_with_msgs(consumer, mock_consumer, msgs, topics=("topic",)):
    """Drive consume() by returning each msg in sequence then stopping the loop."""
    queue = list(msgs)

    def poll_side_effect(timeout):
        if queue:
            return queue.pop(0)
        consumer._running = False
        return None

    mock_consumer.poll.side_effect = poll_side_effect
    return list(consumer.consume(list(topics)))


class TestRawDataConsumer:
    @patch("modules.kafka_consumer.consumer.Consumer")
    def test_consume_yields_decoded_payload(self, mock_consumer_cls):
        mock_consumer = MagicMock()
        mock_consumer_cls.return_value = mock_consumer
        payload = {"symbol": "AAPL", "price": 150.0}

        consumer = RawDataConsumer("localhost:9092")
        results = _consume_with_msgs(consumer, mock_consumer, [_make_msg(payload)])

        assert results == [payload]

    @patch("modules.kafka_consumer.consumer.Consumer")
    def test_consume_skips_none_poll_result(self, mock_consumer_cls):
        mock_consumer = MagicMock()
        mock_consumer_cls.return_value = mock_consumer

        consumer = RawDataConsumer("localhost:9092")
        results = _consume_with_msgs(consumer, mock_consumer, [None])

        assert results == []

    @patch("modules.kafka_consumer.consumer.Consumer")
    def test_consume_skips_partition_eof(self, mock_consumer_cls):
        mock_consumer = MagicMock()
        mock_consumer_cls.return_value = mock_consumer

        consumer = RawDataConsumer("localhost:9092")
        eof_msg = _make_error_msg(KafkaError._PARTITION_EOF)
        results = _consume_with_msgs(consumer, mock_consumer, [eof_msg])

        assert results == []

    @patch("modules.kafka_consumer.consumer.Consumer")
    def test_consume_skips_unknown_topic(self, mock_consumer_cls):
        mock_consumer = MagicMock()
        mock_consumer_cls.return_value = mock_consumer

        consumer = RawDataConsumer("localhost:9092")
        unk_msg = _make_error_msg(KafkaError.UNKNOWN_TOPIC_OR_PART)
        results = _consume_with_msgs(consumer, mock_consumer, [unk_msg])

        assert results == []

    @patch("modules.kafka_consumer.consumer.Consumer")
    def test_consume_closes_consumer_on_exit(self, mock_consumer_cls):
        mock_consumer = MagicMock()
        mock_consumer_cls.return_value = mock_consumer

        consumer = RawDataConsumer("localhost:9092")
        _consume_with_msgs(consumer, mock_consumer, [])

        mock_consumer.close.assert_called_once()

    @patch("modules.kafka_consumer.consumer.Consumer")
    def test_consume_subscribes_to_given_topics(self, mock_consumer_cls):
        mock_consumer = MagicMock()
        mock_consumer_cls.return_value = mock_consumer

        consumer = RawDataConsumer("localhost:9092")
        _consume_with_msgs(consumer, mock_consumer, [], topics=["topic_a", "topic_b"])

        mock_consumer.subscribe.assert_called_once_with(["topic_a", "topic_b"])

    @patch("modules.kafka_consumer.consumer.Consumer")
    def test_shutdown_sets_running_false(self, mock_consumer_cls):
        mock_consumer_cls.return_value = MagicMock()
        consumer = RawDataConsumer("localhost:9092")
        assert consumer._running is True
        consumer._shutdown(None, None)
        assert consumer._running is False

    @patch("modules.kafka_consumer.consumer.Consumer")
    def test_consume_yields_multiple_messages(self, mock_consumer_cls):
        mock_consumer = MagicMock()
        mock_consumer_cls.return_value = mock_consumer
        payloads = [{"symbol": "AAPL"}, {"symbol": "MSFT"}, {"symbol": "GOOG"}]

        consumer = RawDataConsumer("localhost:9092")
        results = _consume_with_msgs(consumer, mock_consumer, [_make_msg(p) for p in payloads])

        assert results == payloads
