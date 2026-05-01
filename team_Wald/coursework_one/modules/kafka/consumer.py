"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Kafka Consumer for news article ingestion into MongoDB
Project : CW1 - Value + News Sentiment Strategy

Provides Kafka consumer functionality for the pipeline.  Subscribes
to the ``news-articles`` topic and stores messages in MongoDB.

This module re-exports ``EventConsumer`` from ``kafka_handler.py``
using the naming convention specified in the project structure (Issue 8).

Usage::

    consumer = EventConsumer(topic="news-articles")
    consumer.consume(callback=lambda msg: mongo.insert_one("raw_news_articles", msg))
"""

from modules.kafka.kafka_handler import EventConsumer, get_event_consumer  # noqa: F401

__all__ = ["EventConsumer", "get_event_consumer"]
