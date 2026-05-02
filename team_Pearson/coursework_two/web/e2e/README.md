# CW2 Web E2E Smoke Tests

These Playwright tests cover the reviewer-facing browser flow:

- load the CW2 workbench;
- open Report Studio;
- confirm LLM connector and report output panels render;
- open the scenario selector modal.

Run them from `coursework_two` after the FastAPI web server is running:

```powershell
$env:CW2_WEB_BASE_URL = "http://127.0.0.1:8011"
npx playwright test web/e2e/cw2_smoke.spec.js
```

The tests are intentionally smoke-level. Long backtest execution is covered by
Python API/job contract tests and the pipeline tests rather than by a browser
test that would be slow and brittle in CI.
