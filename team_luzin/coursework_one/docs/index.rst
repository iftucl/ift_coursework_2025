Investment Strategy Data Pipeline Documentation
===================================================

Welcome to the comprehensive documentation for the Investment Strategy Data Pipeline. This project implements a sophisticated multi-stage data processing system for analyzing and executing quantitative investment strategies.

.. toctree::
   :maxdepth: 2
   :caption: Getting Started
   :hidden:

   installation
   quickstart
   architecture

.. toctree::
   :maxdepth: 2
   :caption: User Guide
   :hidden:

   usage
   configuration

.. toctree::
   :maxdepth: 2
   :caption: API Reference
   :hidden:

   api/index
   api/modules
   api/processing
   api/signals
   api/database
   api/storage

.. toctree::
   :maxdepth: 1
   :caption: Additional Resources
   :hidden:

   troubleshooting
   faq

Project Overview
================

The Investment Strategy Data Pipeline is a comprehensive system for:

- **Data Collection**: Ingesting market data from multiple sources
- **Risk Analysis**: Computing Value-at-Risk (VAR) and volatility metrics
- **Portfolio Selection**: Identifying optimal stocks based on multiple factors
- **Signal Generation**: Creating trading signals using technical indicators
- **Data Export**: Storing results in PostgreSQL, MinIO, and MongoDB

Key Features
============

- **Multi-Stage Pipeline**: 4-step processing pipeline with independent modules
- **Modular Design**: Pluggable components for easy extension
- **Comprehensive Risk Metrics**: VAR-95, ATR, sector exposure analysis
- **Technical Indicators**: MACD, momentum, liquidity analysis
- **Database Integration**: PostgreSQL for structured data, MongoDB for documents
- **Object Storage**: MinIO for data lake implementation
- **Test Coverage**: Comprehensive unit tests with 80%+ coverage target
- **Documentation**: Full Sphinx documentation with API reference

Technology Stack
================

- **Language**: Python 3.10+
- **Data Processing**: pandas, numpy, yfinance
- **Databases**: PostgreSQL, MongoDB
- **Storage**: MinIO (S3-compatible)
- **Testing**: pytest, coverage
- **Documentation**: Sphinx with Napoleon extension
- **Dependency Management**: Poetry

Quick Links
===========

- :doc:`Installation Guide <installation>`
- :doc:`Quick Start <quickstart>`
- :doc:`Architecture Overview <architecture>`
- :doc:`API Reference <api/index>`
- :doc:`Usage Instructions <usage>`

Project Structure
=================

.. code-block:: text

    coursework_one/
    ├── main.py                  # Primary entry point
    ├── run_pipeline.py          # CLI orchestrator with scheduling
    ├── config/                  # Configuration files
    │   └── conf.yaml            # Credentials and settings template
    ├── modules/                 # Core processing modules
    │   ├── db/                  # Database connectivity
    │   ├── input/               # Data ingestion
    │   ├── processing/          # Risk and factor calculations
    │   ├── signals/             # Trading signal generation
    │   ├── output/              # Results export
    │   ├── data/                # Data utilities
    │   ├── extraction/          # Price data extraction
    │   └── storage/             # MinIO and other storage
    ├── test/                    # Comprehensive test suite
    ├── static/                  # Example outputs
    ├── docs/                    # Sphinx documentation
    ├── pyproject.toml           # Poetry dependency management
    ├── pytest.ini               # Test configuration
    └── README.md                # Project README

Pipeline Output Summary
=======================

The system processes 678 stocks through a multi-stage pipeline:

1. **Step 1**: VAR-95 and ATR-14 calculation → 597 stocks (88.1%)
2. **Step 2**: Composite portfolio selection → 130 stocks (19.2%)
3. **Step 3**: Trading signal generation → 335 BUY signals (49.4%)
4. **Step 4**: Analytics export to MinIO

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
