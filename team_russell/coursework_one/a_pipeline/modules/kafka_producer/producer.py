"""Kafka producer that publishes raw market and financial data to topics."""

import json
import logging

from confluent_kafka import Producer

logger = logging.getLogger(__name__)


class RawDataProducer:
    """Wraps a Confluent Kafka Producer for publishing raw data messages.

    Args:
        bootstrap_servers: Kafka broker address (e.g. 'localhost:9092').
    """

    def __init__(self, bootstrap_servers: str) -> None:
        self._producer = Producer({"bootstrap.servers": bootstrap_servers})

    def publish(self, topic: str, symbol: str, data: dict) -> None:
        """Publish a message to a Kafka topic.

        Args:
            topic: Target Kafka topic name.
            symbol: Ticker symbol used as the message key.
            data: Payload dict to serialise as JSON.
        """
        self._producer.produce(
            topic,
            key=symbol.encode("utf-8"),
            value=json.dumps(data).encode("utf-8"),
            callback=self._delivery_report,
        )
        self._producer.poll(0)

    def flush(self) -> None:
        """Wait for all outstanding messages to be delivered."""
        self._producer.flush()

    @staticmethod
    def _delivery_report(err, msg) -> None:
        if err:
            logger.error(f"Message delivery failed: {err}")
        else:
            logger.debug(f"Delivered to {msg.topic()} [partition {msg.partition()}]")
