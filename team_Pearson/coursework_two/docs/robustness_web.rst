Robustness and Web Workbench
============================

Robustness Part Map
-------------------

Part 1 to Part 5 are designed around the formal quarterly-rebalanced baseline. The
tests should use the formal run, formal config, and clean 2026-04-20 data snapshot.
They should not mix legacy 2026-04-24 reports or historical sweep outputs.

The evidence pack is organized so that each robustness section can be traced to
source CSV, chart, and report-summary artifacts. Transaction-cost sensitivity,
normal/stress regime attribution, ablation, stochastic perturbation, and benchmark
comparisons are all routed through this evidence layer.

Web Data Architecture
---------------------

The web application is a control surface. It does not own the strategy logic. It
calls the API layer, which locates configs, runs scripts, reads output artifacts, and
returns normalized JSON for cards, charts, report history, and export buttons.

LLM Connector
-------------

The LLM connector supports provider-specific request formats while keeping API URL,
model selection, temperature, system prompt, and user instruction as explicit setup
state. Model discovery uses the selected provider's model-list endpoint when an API
key is available.
