"""
Tests for the Kafka producer and consumer re-export modules.

Tests that modules/kafka/producer.py and modules/kafka/consumer.py
correctly re-export EventProducer, EventConsumer from kafka_handler.
"""

from modules.kafka.consumer import EventConsumer, get_event_consumer
from modules.kafka.kafka_handler import EventConsumer as HandlerConsumer
from modules.kafka.kafka_handler import EventProducer as HandlerProducer
from modules.kafka.kafka_handler import get_event_consumer as handler_get_consumer
from modules.kafka.kafka_handler import get_event_producer as handler_get_producer
from modules.kafka.producer import EventProducer, get_event_producer


class TestProducerReExport:
    """Tests that producer.py correctly re-exports from kafka_handler."""

    def test_event_producer_is_same_class(self):
        assert EventProducer is HandlerProducer

    def test_get_event_producer_is_same_function(self):
        assert get_event_producer is handler_get_producer

    def test_producer_all_exports(self):
        from modules.kafka import producer

        assert "EventProducer" in producer.__all__
        assert "get_event_producer" in producer.__all__


class TestConsumerReExport:
    """Tests that consumer.py correctly re-exports from kafka_handler."""

    def test_event_consumer_is_same_class(self):
        assert EventConsumer is HandlerConsumer

    def test_get_event_consumer_is_same_function(self):
        assert get_event_consumer is handler_get_consumer

    def test_consumer_all_exports(self):
        from modules.kafka import consumer

        assert "EventConsumer" in consumer.__all__
        assert "get_event_consumer" in consumer.__all__
