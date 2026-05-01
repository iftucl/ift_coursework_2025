# Documentation Workspace

Terminology reminder for shared CW1/CW2 documentation:

- `CW1 as_of` means extraction or audit date on upstream provider-facing records
- `CW2 as_of_date` means feature / portfolio snapshot date and downstream decision date
- `CW2 signal_as_of_date` means the factor/event signal anchor date used by daily update-decision monitoring when it differs from the calendar `run_date`

The names are similar but refer to different layers in the platform.
They should not be treated as interchangeable join keys.
In particular, `CW1 as_of` is not the same business concept as `CW2 as_of_date`.

Manual Sphinx build from project root:

```bash
cd team_Pearson/coursework_one
poetry run python scripts/build_sphinx_docs.py --clean
```

Generated site entrypoint:

- `docs/sphinx/build/html/index.html`

Operational automation:

- Sphinx HTML is also built automatically by the Airflow DAG `cw1_pipeline_and_docs`.
