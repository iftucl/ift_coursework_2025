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
- **Data Export**: Storing results in PostgreSQL and optional MinIO storage

Key Features
============

- **Multi-Stage Pipeline**: 4-step processing pipeline with independent modules
- **Modular Design**: Pluggable components for easy extension
- **Comprehensive Risk Metrics**: VAR-95, ATR, sector exposure analysis
- **Technical Indicators**: MACD, momentum, liquidity analysis
- **Database Integration**: PostgreSQL for structured data
- **Object Storage**: MinIO for optional data lake
- **Test Coverage**: Comprehensive unit tests with 80%+ coverage target
- **Documentation**: Full Sphinx documentation with API reference

Technology Stack
================

- **Language**: Python 3.9+
- **Data Processing**: pandas, numpy, yfinance
- **Database**: PostgreSQL
- **Storage**: MinIO (S3-compatible), local filesystem
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
    ├── main.py                  # Official entry point (thin wrapper)
    ├── run_pipeline.py          # Core orchestration engine
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

Pipeline Stages
===============

The system processes 600+ securities through a multi-stage pipeline:

1. **Step 1**: Risk metrics calculation (VAR-95, ATR-14) across all eligible securities
2. **Step 2**: Portfolio selection via sector-balanced composite scoring
3. **Step 3**: Trading signal generation using technical indicators (MACD, ATR, liquidity filters)
4. **Step 4**: Analytics export to local storage and optional MinIO

Run the pipeline to see exact output counts for your data and analysis date.

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
