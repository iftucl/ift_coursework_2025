Usage Instructions
==================

Main Pipeline
-------------

``Main.py`` is the orchestration entrypoint. It supports scenario-aware execution,
monitor/update-decision modes, and report-oriented workflows. Strategy parameters
come from YAML and validated config objects rather than local script edits.

Web Workbench
-------------

The browser workbench exposes scenario management, robustness inspection, report
generation, and LLM connector setup. The page reads live artifacts from ``outputs``
and API endpoints rather than relying on static placeholder values.

Formal Strategy Frequency
-------------------------

The formal strategy generates portfolio target weights quarterly and executes
quarterly rebalances with an execution lag. Performance, turnover, drawdown, and
other diagnostics are recorded at monthly holding-period frequency. Monthly
monitoring snapshots do not imply monthly re-optimization.

Reports
-------

AI-assisted reports are generated from structured data context, latest robustness
artifacts, and selected benchmark comparisons. Exporters can create text-based PDF
and Word outputs using the same report evidence pack.
