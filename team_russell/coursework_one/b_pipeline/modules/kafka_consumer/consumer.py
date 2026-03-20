"""Kafka consumer that reads raw data messages published by Pipeline A."""

import json
import logging
import signal
from typing import Generator

from confluent_kafka import Consumer, KafkaError, KafkaException

logger = logging.getLogger(__name__)


class RawDataConsumer:
    """Consumes messages from one or more Kafka topics and yields parsed dicts.

    Args:
        bootstrap_servers: Kafka broker address.
        group_id: Consumer group ID (allows resuming from last offset).
    """

    def __init__(self, bootstrap_servers: str, group_id: str = "russell_b_pipeline") -> None:
        self._consumer = Consumer(
            {
                "bootstrap.servers": bootstrap_servers,
                "group.id": group_id,
                "auto.offset.reset": "earliest",
                "enable.auto.commit": True,
            }
        )
        self._running = True
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, signum, frame) -> None:
        logger.info("Shutdown signal received — stopping consumer.")
        self._running = False

    def consume(self, topics: list, poll_timeout: float = 1.0) -> Generator[dict, None, None]:
        """Subscribe to topics and yield decoded message payloads.

        Args:
            topics: List of Kafka topic names to subscribe to.
            poll_timeout: Seconds to wait per poll call.

        Yields:
            Decoded message dict from each Kafka message.
        """
        self._consumer.subscribe(topics)
        logger.info(f"Subscribed to topics: {topics}")

        try:
            while self._running:
                msg = self._consumer.poll(poll_timeout)

                if msg is None:
                    continue

                if msg.error():
                    code = msg.error().code()
                    if code == KafkaError._PARTITION_EOF:
                        logger.debug(f"End of partition {msg.partition()} for topic {msg.topic()}")
                        continue
                    if code == KafkaError.UNKNOWN_TOPIC_OR_PART:
                        logger.info("Topics not yet created — waiting for Pipeline A to publish...")
                        continue
                    raise KafkaException(msg.error())

                try:
                    payload = json.loads(msg.value().decode("utf-8"))
                    yield payload
                except json.JSONDecodeError as exc:
                    logger.error(f"Failed to decode message: {exc}")

        finally:
            self._consumer.close()
            logger.info("Kafka consumer closed.")
