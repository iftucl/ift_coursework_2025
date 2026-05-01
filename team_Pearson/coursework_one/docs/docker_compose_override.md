# Docker Compose Override

The repository-root `docker-compose.yml` is treated as upstream coursework
infrastructure and is intentionally not modified by Team Pearson.

Team Pearson runtime additions are kept in
`team_Pearson/coursework_one/docker-compose.pearson.override.yml`. Use it with
the upstream compose file from the repository root:

```bash
docker compose -f docker-compose.yml \
  -f team_Pearson/coursework_one/docker-compose.pearson.override.yml up -d \
  postgres_db mongo_db miniocw minio_client_cw team_pearson_redis kafka_cw airflow_cw
```

The override owns the Pearson-specific services and settings:

- Kafka for optional event audit flows.
- Redis for runtime state, rate limiting, and audit cursors.
- Airflow for CW1/CW2 orchestration.
- The CW2 Kafka audit consumer.
- Pearson-specific MinIO and pgAdmin volume overrides.

The only current difference between the previous Pearson top-level compose file
and the upstream compose file was an end-of-file newline. There was no
functional top-level compose delta to migrate.
