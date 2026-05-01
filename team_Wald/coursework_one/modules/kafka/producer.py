"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Kafka Producer for news article event publishing
Project : CW1 - Value + News Sentiment Strategy

Provides Kafka producer functionality for the pipeline.  Publishes
news articles and value metrics as JSON messages to configured topics.

This module re-exports ``EventProducer`` from ``kafka_handler.py``
using the naming convention specified in the project structure (Issue 8).

Topics:
  - ``news-articles``: Raw news articles as they are fetched
  - ``value-metrics``: Computed value and sentiment scores

Degrades gracefully if Kafka is unavailable — the pipeline writes
directly to PostgreSQL/MongoDB instead.
"""

from modules.kafka.kafka_handler import EventProducer, get_event_producer  # noqa: F401

__all__ = ["EventProducer", "get_event_producer"]
