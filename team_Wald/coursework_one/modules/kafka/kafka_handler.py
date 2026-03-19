"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Apache Kafka event producer for the pipeline
Project : CW1 - Value + News Sentiment Strategy

Publishes news article events and value metric events to Kafka
topics for decoupled, event-driven processing.

Topics:
  - news-articles : Raw news articles as they are fetched
  - value-metrics : Computed value and sentiment scores

The spec states: "To handle data ingestion and processing, you can
leverage on Apache Kafka."  This module implements the producer side;
downstream consumers can be added in CW2.

Degrades gracefully if Kafka is unavailable — the pipeline writes
directly to databases instead.
"""

import json
import os
from typing import Callable

from modules.utils.logger import pipeline_logger

try:
    from kafka import KafkaConsumer, KafkaProducer
    from kafka.errors import KafkaError

    KAFKA_AVAILABLE = True
except ImportError:
    KafkaProducer = None
    KafkaConsumer = None
    KafkaError = Exception
    KAFKA_AVAILABLE = False


class EventProducer:
    """Kafka producer for publishing pipeline events.

    Serialises events as JSON and publishes to configured topics.
    Uses lazy initialisation for graceful degradation.

    :param bootstrap_servers: Kafka broker address
    :type bootstrap_servers: str
    """

    def __init__(self, bootstrap_servers: str = None):
        self.bootstrap_servers = bootstrap_servers or os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        self._producer = None

    @property
    def producer(self):
        """Lazy-initialise the Kafka producer.

        :return: KafkaProducer or None
        """
        if self._producer is None:
            if not KAFKA_AVAILABLE:
                pipeline_logger.warning("kafka-python not installed — Kafka disabled")
                return None
            try:
                self._producer = KafkaProducer(
                    bootstrap_servers=self.bootstrap_servers,
                    value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
                    key_serializer=lambda k: k.encode("utf-8") if k else None,
                    acks="all",
                    retries=3,
                )
                pipeline_logger.info("Kafka producer connected to %s", self.bootstrap_servers)
            except Exception as e:
                pipeline_logger.warning("Could not connect to Kafka: %s", e)
                self._producer = None
        return self._producer

    def publish_event(self, topic: str, key: str, payload: dict):
        """Publish a single event to a Kafka topic.

        :param topic: Target Kafka topic
        :type topic: str
        :param key: Message key (typically ticker symbol)
        :type key: str
        :param payload: Event data as dictionary
        :type payload: dict
        """
        if self.producer is None:
            return
        try:
            self.producer.send(topic, key=key, value=payload)
        except Exception as e:
            pipeline_logger.warning("Failed to publish to %s/%s: %s", topic, key, e)

    def publish_batch(self, topic: str, events: list[dict], key_field: str = "company_id"):
        """Publish a batch of events to a Kafka topic.

        :param topic: Target topic
        :type topic: str
        :param events: List of event dicts
        :type events: list[dict]
        :param key_field: Dict key to use as Kafka message key
        :type key_field: str
        """
        if self.producer is None or not events:
            return
        for event in events:
            key = str(event.get(key_field, "unknown"))
            self.publish_event(topic, key, event)
        self.producer.flush(timeout=10)
        pipeline_logger.info("Published %d events to %s", len(events), topic)

    def flush(self):
        """Flush all pending messages."""
        if self._producer is not None:
            self._producer.flush(timeout=10)

    def close(self):
        """Flush and close the producer."""
        self.flush()
        if self._producer is not None:
            self._producer.close()
            self._producer = None


class EventConsumer:
    """Kafka consumer for reading pipeline events.

    :param bootstrap_servers: Kafka broker address
    :type bootstrap_servers: str
    :param group_id: Consumer group identifier
    :type group_id: str
    :param topics: List of topics to subscribe to
    :type topics: list[str]
    """

    def __init__(
        self,
        bootstrap_servers: str = None,
        group_id: str = "cw1-sentiment-consumer",
        topics: list[str] = None,
    ):
        self.bootstrap_servers = bootstrap_servers or os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        self.group_id = group_id
        self.topics = topics or ["news-articles", "value-metrics"]
        self._consumer = None

    @property
    def consumer(self):
        """Lazy-initialise the Kafka consumer.

        :return: KafkaConsumer or None
        """
        if self._consumer is None:
            if not KAFKA_AVAILABLE:
                pipeline_logger.warning("kafka-python not installed — Kafka consumer disabled")
                return None
            try:
                self._consumer = KafkaConsumer(
                    *self.topics,
                    bootstrap_servers=self.bootstrap_servers,
                    group_id=self.group_id,
                    auto_offset_reset="earliest",
                    value_deserializer=lambda v: json.loads(v.decode("utf-8")),
                )
                pipeline_logger.info("Kafka consumer subscribed to %s", self.topics)
            except Exception as e:
                pipeline_logger.warning("Could not create Kafka consumer: %s", e)
                self._consumer = None
        return self._consumer

    def consume(self, callback: Callable, max_messages: int = 100, timeout_ms: int = 1000):
        """Consume messages and pass to a callback function.

        :param callback: Function(topic: str, payload: dict) called per message
        :type callback: Callable
        :param max_messages: Maximum messages to consume
        :type max_messages: int
        :param timeout_ms: Poll timeout in milliseconds
        :type timeout_ms: int
        """
        if self.consumer is None:
            return
        count = 0
        records = self.consumer.poll(timeout_ms=timeout_ms, max_records=max_messages)
        for tp, messages in records.items():
            for msg in messages:
                try:
                    callback(tp.topic, msg.value)
                    count += 1
                except Exception as e:
                    pipeline_logger.warning("Error processing Kafka message: %s", e)
        pipeline_logger.info("Consumed %d messages", count)

    def close(self):
        """Close the Kafka consumer."""
        if self._consumer is not None:
            self._consumer.close()
            self._consumer = None


def get_event_producer(kafka_config: dict = None) -> EventProducer:
    """Factory function to create an EventProducer from config.

    :param kafka_config: Kafka config section from conf.yaml
    :type kafka_config: dict or None
    :return: Configured EventProducer
    :rtype: EventProducer
    """
    if kafka_config:
        return EventProducer(bootstrap_servers=kafka_config.get("BootstrapServers"))
    return EventProducer()


def get_event_consumer(kafka_config: dict = None) -> EventConsumer:
    """Factory function to create an EventConsumer from config.

    :param kafka_config: Kafka config section from conf.yaml
    :type kafka_config: dict or None
    :return: Configured EventConsumer
    :rtype: EventConsumer
    """
    if kafka_config:
        return EventConsumer(bootstrap_servers=kafka_config.get("BootstrapServers"))
    return EventConsumer()
