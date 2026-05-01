One-Command Full Workflow Runbook
=================================

Purpose
-------

The full workflow command is the single command path for checking that the CW2
delivery is connected end to end. It checks quality gates, confirms the local
stores are reachable, runs the formal full-chain strategy/report path,
refreshes robustness evidence surfaces, and verifies that the web API can read
the connected outputs.

One-Line Command
----------------

From ``team_Pearson/coursework_two`` on Windows:

.. code-block:: powershell

   ..\.venv\Scripts\python.exe scripts\full_workflow.py --start-services --serve

The same command can be launched by double-clicking:

.. code-block:: text

   Launch_CW2_Full_Workflow.cmd

What It Checks
--------------

The command performs the following stages:

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Stage
     - Check
   * - Quality gate
     - Runs ``black``, ``isort``, ``flake8``, ``bandit``, Sphinx build, and the
       CW2 large-file check. Add ``--include-pytest`` for the full coverage gate.
   * - Infrastructure
     - Checks PostgreSQL, MongoDB, MinIO, Redis, and Kafka socket reachability,
       then verifies that PostgreSQL can be queried and the
       ``systematic_equity`` schema exists.
   * - Full strategy chain
     - Runs ``scripts/run_full_chain.py`` from the formal configuration. This
       initializes schemas, runs the CW1-to-CW2 handoff, writes quarterly target
       snapshots, runs the stored-strategy backtest, performs analysis, and
       builds a report package.
   * - Robustness bridge
     - Rebuilds the requirement-facing robustness summary for the formal
       baseline run and persists robustness outputs into PostgreSQL, so the web
       robustness views can read the evidence pack.
   * - Web/API
     - Starts or reuses the FastAPI server, checks ``/health``, the web shell,
       summary cards, run history, artifacts, robustness dashboard, acceptance
       matrix, report evidence, and workbench context.

Output
------

Each run writes a machine-readable summary to:

.. code-block:: text

   outputs/web_state/full_workflow/latest.json

Timestamped summaries are stored in the same directory. The web URL is printed
at the end of a successful run. When ``--serve`` is used, the API server remains
open until interrupted with ``Ctrl+C``.

Common Options
--------------

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Option
     - Meaning
   * - ``--start-services``
     - Runs Docker Compose for the shared PostgreSQL, MongoDB, MinIO, Redis, and
       Kafka services before checking connectivity.
   * - ``--serve``
     - Keeps the web server open after successful checks.
   * - ``--include-pytest``
     - Adds the full CW2 pytest coverage run. This is slower but verifies the
       80 percent coverage gate.
   * - ``--company-limit``
     - Optional full-chain universe cap for debugging. Omit it for the
       configured full universe used by the full workflow command.
   * - ``--smoke-profile``
     - Optional fast end-to-end smoke validation profile. Omit it for the
       default full workflow path and for formal evidence. ``--quick-profile``
       is accepted as an alias.
   * - ``--smoke-lookback-years``
     - Optional lookback window for ``--smoke-profile``. It has no role in the
       default full workflow path. ``--quick-lookback-years`` is accepted as an
       alias.
   * - ``--skip-chain``
     - Skips the full strategy/report chain and only checks quality,
       infrastructure, robustness evidence, and web surfaces.
   * - ``--skip-robustness``
     - Skips robustness evidence rebuilding when only the strategy/web path is
       being tested.

Interpretation
--------------

The full workflow command confirms that the system is wired together through
the full strategy/report path. It does not replace the formal run id
``6905e84b-9e16-4106-8c0f-cd9ecce56728`` and it does not overwrite the final
formal robustness result set. Full formal robustness remains reproducible
through ``scripts/run_formal_fast_robustness.py`` and the formal evidence pack
under ``outputs/robustness``.
