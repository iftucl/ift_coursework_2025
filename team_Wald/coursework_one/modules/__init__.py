"""
CW1 Value + News Sentiment Strategy — Module Package
=====================================================

This package contains all pipeline modules organised by concern:

- **db/**          — Database connection wrappers (PostgreSQL, MongoDB, MinIO)
- **extraction/**  — Data extraction from external APIs (Yahoo Finance, GDELT)
- **processing/**  — Factor computation (value ratios, VADER sentiment, composite)
- **loading/**     — Data loading into storage systems (upsert, document insert)
- **kafka/**       — Apache Kafka producer and consumer for news streaming
- **utils/**       — Shared utilities (config, logging, CLI)
"""
