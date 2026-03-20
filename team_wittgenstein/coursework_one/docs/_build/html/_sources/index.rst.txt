Coursework One — Data Pipeline Documentation
=============================================

A data pipeline for a 130/30 multi-factor equity strategy, built for
Big Data in Quantitative Finance (Coursework One).

The pipeline fetches daily prices, quarterly financials, and risk-free
rates from multiple sources, validates the data, and loads it into
PostgreSQL for downstream factor modelling.

.. toctree::
   :maxdepth: 2
   :caption: Contents

   installation
   usage
   architecture
   api/data_collector
   api/data_writer
   api/data_validator
   api/connections
