#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="team_Pearson/coursework_two/outputs/handoff"
EXPORT_DATE="$(date +%Y%m%d)"
LABEL="formal_s30"
REFERENCE_RUN_ID=""
REFERENCE_RUN_NAME=""
CONFIG_PATH=""

POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-postgres_db_cw}"
MONGO_CONTAINER="${MONGO_CONTAINER:-mongo_db_cw}"
MINIO_CLIENT_CONTAINER="${MINIO_CLIENT_CONTAINER:-minio_client_cw}"
MINIO_ALIAS="${MINIO_ALIAS:-cw}"
MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://miniocw:9000}"
MINIO_ACCESS_KEY="${MINIO_ACCESS_KEY:-ift_bigdata}"
MINIO_SECRET_KEY="${MINIO_SECRET_KEY:-minio_password}"
MINIO_BUCKET="${MINIO_BUCKET:-csreport}"

usage() {
  cat <<'EOF'
Usage:
  team_Pearson/coursework_two/scripts/export_repro_bundle.sh [options]

Options:
  --out-dir PATH              Output directory for tarballs and manifests
  --export-date YYYYMMDD      Date stamp to embed in artifact names
  --label LABEL               Logical label for the bundle
  --reference-run-id ID       Optional formal reference run_id
  --reference-run-name NAME   Optional formal reference run_name
  --config-path PATH          Optional reference config path
  -h, --help                  Show this help message
EOF
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

sha256_file() {
  shasum -a 256 "$1" | awk '{print $1}'
}

file_size_bytes() {
  if stat -f '%z' "$1" >/dev/null 2>&1; then
    stat -f '%z' "$1"
  else
    stat -c '%s' "$1"
  fi
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --out-dir)
      OUT_DIR="$2"
      shift 2
      ;;
    --export-date)
      EXPORT_DATE="$2"
      shift 2
      ;;
    --label)
      LABEL="$2"
      shift 2
      ;;
    --reference-run-id)
      REFERENCE_RUN_ID="$2"
      shift 2
      ;;
    --reference-run-name)
      REFERENCE_RUN_NAME="$2"
      shift 2
      ;;
    --config-path)
      CONFIG_PATH="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

require_cmd docker
require_cmd tar
require_cmd shasum
require_cmd python3

mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"

POSTGRES_STEM="cw2_postgres_export_${EXPORT_DATE}_${LABEL}"
UPSTREAM_STEM="cw2_upstream_export_${EXPORT_DATE}_${LABEL}"
POSTGRES_TARBALL="${OUT_DIR}/${POSTGRES_STEM}.tar.gz"
UPSTREAM_TARBALL="${OUT_DIR}/${UPSTREAM_STEM}.tar.gz"
MANIFEST_PATH="${OUT_DIR}/cw2_repro_bundle_${EXPORT_DATE}_${LABEL}.json"

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/cw2_export_bundle.XXXXXX")"
cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

POSTGRES_DIR="${WORK_DIR}/${POSTGRES_STEM}"
UPSTREAM_DIR="${WORK_DIR}/${UPSTREAM_STEM}"
mkdir -p "${POSTGRES_DIR}" "${UPSTREAM_DIR}/mongo" "${UPSTREAM_DIR}/minio_raw"

echo "Exporting PostgreSQL from ${POSTGRES_CONTAINER} ..."
docker exec "${POSTGRES_CONTAINER}" sh -lc "rm -f /tmp/${POSTGRES_STEM}.dump /tmp/${POSTGRES_STEM}_schema.sql"
docker exec "${POSTGRES_CONTAINER}" sh -lc "pg_dump -U postgres -Fc -d fift -f /tmp/${POSTGRES_STEM}.dump"
docker exec "${POSTGRES_CONTAINER}" sh -lc "pg_dump -U postgres -d fift --schema-only -f /tmp/${POSTGRES_STEM}_schema.sql"
docker cp "${POSTGRES_CONTAINER}:/tmp/${POSTGRES_STEM}.dump" "${POSTGRES_DIR}/${POSTGRES_STEM}.dump"
docker cp "${POSTGRES_CONTAINER}:/tmp/${POSTGRES_STEM}_schema.sql" "${POSTGRES_DIR}/${POSTGRES_STEM}_schema.sql"
docker exec "${POSTGRES_CONTAINER}" sh -lc "psql -U postgres -d postgres -Atc \"SELECT pg_database_size('fift');\"" \
  > "${POSTGRES_DIR}/${POSTGRES_STEM}_db_size.txt"
docker exec "${POSTGRES_CONTAINER}" sh -lc "psql -U postgres -d fift -F \$'\\t' -Atc \"SELECT schemaname || '.' || relname, n_live_tup FROM pg_stat_user_tables ORDER BY 1;\"" \
  > "${POSTGRES_DIR}/${POSTGRES_STEM}_table_stats.tsv"
docker exec "${POSTGRES_CONTAINER}" sh -lc "rm -f /tmp/${POSTGRES_STEM}.dump /tmp/${POSTGRES_STEM}_schema.sql"

cat > "${POSTGRES_DIR}/README.md" <<EOF
# CW2 PostgreSQL export

- generated_at_utc: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
- container: ${POSTGRES_CONTAINER}
- database: fift
- reference_run_id: ${REFERENCE_RUN_ID}
- reference_run_name: ${REFERENCE_RUN_NAME}
- config_path: ${CONFIG_PATH}

This bundle is intended for exact GitHub reproducibility of the current latest
CW2 reference run.
EOF

echo "Exporting MongoDB from ${MONGO_CONTAINER} ..."
docker exec "${MONGO_CONTAINER}" sh -lc "rm -f /tmp/${UPSTREAM_STEM}.archive.gz"
docker exec "${MONGO_CONTAINER}" sh -lc "mongodump --gzip --archive=/tmp/${UPSTREAM_STEM}.archive.gz --db ift_cw"
docker cp "${MONGO_CONTAINER}:/tmp/${UPSTREAM_STEM}.archive.gz" "${UPSTREAM_DIR}/mongo/${UPSTREAM_STEM}.archive.gz"
docker exec "${MONGO_CONTAINER}" sh -lc "mongosh ift_cw --quiet --eval \"db.getCollectionInfos().map(c => c.name).sort().forEach(function(name){ print(name + '\\t' + db.getCollection(name).countDocuments({})) })\"" \
  > "${UPSTREAM_DIR}/mongo/mongo_collection_counts.tsv"
docker exec "${MONGO_CONTAINER}" sh -lc "rm -f /tmp/${UPSTREAM_STEM}.archive.gz"

echo "Exporting MinIO raw objects from ${MINIO_CLIENT_CONTAINER} ..."
docker exec "${MINIO_CLIENT_CONTAINER}" sh -lc "rm -rf /tmp/${UPSTREAM_STEM}"
docker exec "${MINIO_CLIENT_CONTAINER}" sh -lc "MC_BIN=\$(command -v mc || echo /usr/bin/mc); \
  \"\$MC_BIN\" alias set ${MINIO_ALIAS} ${MINIO_ENDPOINT} ${MINIO_ACCESS_KEY} ${MINIO_SECRET_KEY} >/dev/null && \
  mkdir -p /tmp/${UPSTREAM_STEM} && \
  \"\$MC_BIN\" mirror --overwrite ${MINIO_ALIAS}/${MINIO_BUCKET}/raw/source_a /tmp/${UPSTREAM_STEM}/raw/source_a >/dev/null && \
  \"\$MC_BIN\" mirror --overwrite ${MINIO_ALIAS}/${MINIO_BUCKET}/raw/source_b /tmp/${UPSTREAM_STEM}/raw/source_b >/dev/null"
docker cp "${MINIO_CLIENT_CONTAINER}:/tmp/${UPSTREAM_STEM}/raw" "${UPSTREAM_DIR}/minio_raw/raw"
docker exec "${MINIO_CLIENT_CONTAINER}" sh -lc "rm -rf /tmp/${UPSTREAM_STEM}"

python3 - <<'PY' "${UPSTREAM_DIR}/minio_raw/raw" "${UPSTREAM_DIR}/minio_raw/MANIFEST.json"
import json
import os
import sys
from pathlib import Path

raw_dir = Path(sys.argv[1])
manifest_path = Path(sys.argv[2])
summary = {}
for name in ("source_a", "source_b"):
    root = raw_dir / name
    file_count = 0
    byte_total = 0
    for path in root.rglob("*"):
        if path.is_file():
            file_count += 1
            byte_total += path.stat().st_size
    summary[name] = {"file_count": file_count, "byte_total": byte_total}
manifest_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
PY

cat > "${UPSTREAM_DIR}/README.md" <<EOF
# CW2 upstream export

- generated_at_utc: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
- mongo_container: ${MONGO_CONTAINER}
- minio_client_container: ${MINIO_CLIENT_CONTAINER}
- minio_bucket: ${MINIO_BUCKET}
- reference_run_id: ${REFERENCE_RUN_ID}
- reference_run_name: ${REFERENCE_RUN_NAME}
- config_path: ${CONFIG_PATH}

This bundle contains the frozen MongoDB archive plus MinIO raw/source_a and
raw/source_b trees needed for exact GitHub reproducibility of the current latest
CW2 reference run.
EOF

tar -czf "${POSTGRES_TARBALL}" -C "${WORK_DIR}" "${POSTGRES_STEM}"
tar -czf "${UPSTREAM_TARBALL}" -C "${WORK_DIR}" "${UPSTREAM_STEM}"

POSTGRES_SHA="$(sha256_file "${POSTGRES_TARBALL}")"
UPSTREAM_SHA="$(sha256_file "${UPSTREAM_TARBALL}")"
POSTGRES_SIZE="$(file_size_bytes "${POSTGRES_TARBALL}")"
UPSTREAM_SIZE="$(file_size_bytes "${UPSTREAM_TARBALL}")"

printf '%s  %s\n' "${POSTGRES_SHA}" "$(basename "${POSTGRES_TARBALL}")" > "${POSTGRES_TARBALL}.sha256"
printf '%s  %s\n' "${UPSTREAM_SHA}" "$(basename "${UPSTREAM_TARBALL}")" > "${UPSTREAM_TARBALL}.sha256"

cat > "${MANIFEST_PATH}" <<EOF
{
  "generated_at_utc": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "reference_run_id": "${REFERENCE_RUN_ID}",
  "reference_run_name": "${REFERENCE_RUN_NAME}",
  "config_path": "${CONFIG_PATH}",
  "artifacts": [
    {
      "role": "postgres",
      "file_name": "$(basename "${POSTGRES_TARBALL}")",
      "sha256": "${POSTGRES_SHA}",
      "size_bytes": ${POSTGRES_SIZE}
    },
    {
      "role": "upstream",
      "file_name": "$(basename "${UPSTREAM_TARBALL}")",
      "sha256": "${UPSTREAM_SHA}",
      "size_bytes": ${UPSTREAM_SIZE}
    }
  ]
}
EOF

echo
echo "Created reproducibility bundle assets:"
echo "  ${POSTGRES_TARBALL}"
echo "  ${POSTGRES_TARBALL}.sha256"
echo "  ${UPSTREAM_TARBALL}"
echo "  ${UPSTREAM_TARBALL}.sha256"
echo "  ${MANIFEST_PATH}"
