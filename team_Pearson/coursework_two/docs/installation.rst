Installation Guide
==================

Python Environment
------------------

Use the project virtual environment from ``team_Pearson/.venv``. The CW2 package is
run from ``team_Pearson/coursework_two`` with ``PYTHONPATH`` pointing at the team
workspace so that cross-package imports resolve consistently on Windows and macOS.

Environment Variables
---------------------

Copy ``.env.example`` to a local ``.env`` file and fill only local secrets there.
API keys are not committed. The web interface stores session API keys outside the
public report artifacts and hides saved keys in the browser form.

Local Services
--------------

The research platform expects PostgreSQL-backed analytics tables and optional web
runtime services. The exact database name and credentials should come from the
active config or environment file rather than hard-coded values.

Windows and macOS
-----------------

Windows users can launch the web workbench with ``Launch_CW2_Web.cmd``. macOS or
Unix-like users can run the FastAPI entrypoint directly with the configured Python
environment.
