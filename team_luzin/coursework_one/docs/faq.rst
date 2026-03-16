Frequently Asked Questions (FAQ)
================================

**Q: How long does a complete pipeline run take?**

A: Approximately 2 minutes for 678 stocks (45s VAR + 30s Portfolio + 20s Signals + 15s Export).

**Q: Can I run the pipeline on a specific date?**

A: Yes, use ``--run-date`` option:

.. code-block:: bash

    poetry run python3 main.py --run-date 2026-02-15

**Q: What does the dry-run option do?**

A: Tests the entire pipeline without writing to databases. Useful for validation:

.. code-block:: bash

    poetry run python3 main.py --dry-run

**Q: How do I change the portfolio size?**

A: Edit ``config/conf.yaml``:

.. code-block:: yaml

    processing:
      portfolio_size: 50  # Default is 130

**Q: Can I add more stocks to the universe?**

A: Yes, modify the data loader or load from PostgreSQL company_static table. The system scales to handle more stocks.

**Q: How do I schedule automatic daily runs?**

A: Use cron (Unix) or Task Scheduler (Windows):

.. code-block:: bash

    # Add to crontab
    30 9 * * * cd /path/to/coursework_one && poetry run python3 main.py --frequency daily

**Q: What databases are required?**

A: PostgreSQL is required. MongoDB and MinIO are optional but recommended for complete functionality.

**Q: Can I use a cloud database like AWS RDS?**

A: Yes, just update the connection details in ``config/conf.yaml``:

.. code-block:: yaml

    database:
      host: my-rds-instance.amazonaws.com
      port: 5432
      user: admin
      password: my-password

**Q: How do I handle sensitive credentials?**

A: Use environment variables:

.. code-block:: bash

    export DB_PASSWORD=secure_password
    poetry run python3 main.py

Then in config/conf.yaml:

.. code-block:: yaml

    database:
      password: ${DB_PASSWORD}

**Q: What's the difference between the 130 and 335 outputs?**

A: 
- 130: Selected stocks (Step 2 portfolio selection)
- 335: Trading signals (Step 3 signal generation)

Different stocks may have different signal types (BUY/SELL).

**Q: How do I regenerate HTML documentation?**

A: 

.. code-block:: bash

    cd docs
    poetry run sphinx-build -b html . _build/html
    open _build/html/index.html

**Q: Can I run tests in parallel?**

A: Yes:

.. code-block:: bash

    poetry run pytest -n auto

**Q: How do I reduce memory usage?**

A: 

1. Reduce portfolio_size in config
2. Reduce historical data window
3. Disable intermediate exports
4. Use parallel processing with smaller batches

**Q: What Python versions are supported?**

A: Python 3.10+. Check version:

.. code-block:: bash

    python3 --version

**Q: Can I customize the signal generation?**

A: Yes, modify ``modules/signals/execution_signals.py`` or create a new signal generator.

**Q: How do I export to different formats?**

A: Edit ``config/conf.yaml``:

.. code-block:: yaml

    output:
      format: parquet  # or csv, json

**Q: What's included in the documentation?**

A: 

- Installation guide
- Quick start tutorial
- Architecture overview
- Complete API reference
- Usage instructions
- Troubleshooting guide
- Configuration guide
- This FAQ

**Q: How do I report bugs?**

A: 

1. Check :doc:`troubleshooting` guide
2. Review logs in ``logs/`` directory
3. Run tests to identify issue
4. Check GitHub issues (if applicable)
5. Contact project maintainers

**Q: Can I integrate with external tools?**

A: Yes, the modular design allows integration with other systems. Import modules as libraries or use the database as a data source.

**Q: What's the test coverage?**

A: Target is 80%+. Run coverage report:

.. code-block:: bash

    poetry run pytest --cov=modules --cov-report=html

**Q: How do I add new technical indicators?**

A: Create new module in ``modules/processing/`` and integrate into CompositeScorer or ExecutionSignalGenerator.

**Q: Is multi-threading supported?**

A: Yes, the pipeline uses connection pooling and supports parallel market data downloads.

**Q: How do I monitor CPU/memory usage?**

A: Use system tools:

.. code-block:: bash

    # Linux
    top
    htop
    
    # macOS
    Activity Monitor
    
    # Monitor with stats
    ps aux | grep python3

**Q: Can I backtest historical data?**

A: Yes, run with historical dates:

.. code-block:: bash

    for date in {2026-01-15,2026-02-15,2026-03-15}; do
        poetry run python3 main.py --run-date $date
    done

**Q: What if PostgreSQL connection times out?**

A: Increase timeout in config:

.. code-block:: yaml

    database:
      timeout: 60  # increased from 30

**Q: How do I clear cached data?**

A: 

.. code-block:: bash

    # Clear Python cache
    find . -type d -name __pycache__ -exec rm -rf {} +
    
    # Clear pytest cache
    rm -rf .pytest_cache
    
    # Clear coverage data
    rm -f .coverage

**Q: Can I run multiple pipeline instances?**

A: Not recommended as they would write conflicting data. Use scheduling instead.

**Q: How do I update dependencies?**

A: 

.. code-block:: bash

    poetry update
    poetry install

**Q: What's the difference between quarterly and monthly runs?**

A: Frequency determines when scheduled runs execute. ``--frequency`` is independent from ``--run-date``.

**Q: How do I contribute to the project?**

A: Submit pull requests with improvements. Ensure tests pass and documentation is updated.

For more detailed information, see:

- :doc:`Installation <installation>` guide
- :doc:`Quick Start <quickstart>` tutorial
- :doc:`Architecture <architecture>` overview
- :doc:`API Reference <api/index>` documentation
- :doc:`Troubleshooting <troubleshooting>` guide
