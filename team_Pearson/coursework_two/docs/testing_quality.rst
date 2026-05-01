Testing and Quality Gates
=========================

Required Commands
-----------------

The current coursework quality gate uses:

Install the optional development tooling with ``python -m pip install -r
requirements-dev.txt`` before running the full local gate set.

* ``black --check modules scripts tests api``
* ``isort --check-only modules scripts tests api``
* ``flake8 --jobs=1 modules scripts tests api web``
* ``bandit -c bandit.yaml -r modules api web -ll``
* ``safety check``
* ``pytest tests --cov=modules --cov-report=html``
* ``vulture modules`` followed by manual review or whitelist decisions
* ``python scripts/check_large_files.py --max-mb 5``

The local pre-commit configuration mirrors the format, lint, security, and
large-file checks. ``mypy --strict --follow-imports=skip modules api`` and
``pylint modules api`` are registered as manual gates because the existing
codebase is not yet fully typed or pylint-normalized; they should be promoted
into the default hook list only after their baselines are cleaned without
suppressing meaningful errors.

Coverage Policy
---------------

The minimum overall target is 80 percent. Key modules should be held close to
90 percent line coverage, especially portfolio construction, factor scoring,
and the backtest engine. The backtest engine uses quarterly target/rebalance
logic for the formal strategy while recording monthly holding-period performance
rows, so tests must distinguish cadence of decision-making from cadence of
performance measurement.

Security Policy
---------------

External API calls must validate URL schemes and use explicit provider endpoints.
Secrets stay in local environment files or session state, never in committed
artifacts.

E2E Policy
----------

The Playwright suite in ``web/e2e`` covers the reviewer-critical web flow:
scenario setup, runner queue interaction, run-history visibility, and report
studio output inspection. It is intended to be run against the FastAPI-served
workbench at ``http://127.0.0.1:8011`` after frontend or API changes.
