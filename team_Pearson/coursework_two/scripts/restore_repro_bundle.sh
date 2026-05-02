#!/usr/bin/env bash
set -euo pipefail

BUNDLE_DIR=""
POSTGRES_ARCHIVE=""
UPSTREAM_ARCHIVE=""

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
  team_Pearson/coursework_two/scripts/restore_repro_bundle.sh [options]

Options:
  --bundle-dir PATH         Directory containing the two bundle tarballs
  --postgres-archive PATH   PostgreSQL bundle tarball
  --upstream-archive PATH   Upstream bundle tarball
  -h, --help                Show this help message
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

verify_sidecar_if_present() {
  local archive_path="$1"
  local sidecar_path="${archive_path}.sha256"
  if [ ! -f "${sidecar_path}" ]; then
    echo "No checksum sidecar for ${archive_path}; skipping checksum verification."
    return
  fi

  local expected actual
  expected="$(awk '{print $1}' "${sidecar_path}")"
  actual="$(sha256_file "${archive_path}")"
  if [ "${expected}" != "${actual}" ]; then
    echo "Checksum mismatch for ${archive_path}" >&2
    echo "Expected: ${expected}" >&2
    echo "Actual:   ${actual}" >&2
    exit 1
  fi
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --bundle-dir)
      BUNDLE_DIR="$2"
      shift 2
      ;;
    --postgres-archive)
      POSTGRES_ARCHIVE="$2"
      shift 2
      ;;
    --upstream-archive)
      UPSTREAM_ARCHIVE="$2"
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

if [ -n "${BUNDLE_DIR}" ]; then
  if [ -z "${POSTGRES_ARCHIVE}" ]; then
    POSTGRES_ARCHIVE="$(find "${BUNDLE_DIR}" -maxdepth 1 -type f -name 'cw2_postgres_export_*formal_s30.tar.gz' | sort | tail -n 1)"
    if [ -z "${POSTGRES_ARCHIVE}" ]; then
      POSTGRES_ARCHIVE="$(find "${BUNDLE_DIR}" -maxdepth 1 -type f -name 'cw2_postgres_export_*.tar.gz' | sort | tail -n 1)"
    fi
  fi
  if [ -z "${UPSTREAM_ARCHIVE}" ]; then
    UPSTREAM_ARCHIVE="$(find "${BUNDLE_DIR}" -maxdepth 1 -type f -name 'cw2_upstream_export_*formal_s30.tar.gz' | sort | tail -n 1)"
    if [ -z "${UPSTREAM_ARCHIVE}" ]; then
      UPSTREAM_ARCHIVE="$(find "${BUNDLE_DIR}" -maxdepth 1 -type f -name 'cw2_upstream_export_*.tar.gz' | sort | tail -n 1)"
    fi
  fi
fi

if [ -z "${POSTGRES_ARCHIVE}" ] || [ -z "${UPSTREAM_ARCHIVE}" ]; then
  echo "Both PostgreSQL and upstream archives are required." >&2
  exit 1
fi

if [ ! -f "${POSTGRES_ARCHIVE}" ] || [ ! -f "${UPSTREAM_ARCHIVE}" ]; then
  echo "Archive file not found." >&2
  exit 1
fi

verify_sidecar_if_present "${POSTGRES_ARCHIVE}"
verify_sidecar_if_present "${UPSTREAM_ARCHIVE}"

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/cw2_restore_bundle.XXXXXX")"
cleanup() {
  rm -rf "${WORK_DIR}"
}
trap cleanup EXIT

tar -xzf "${POSTGRES_ARCHIVE}" -C "${WORK_DIR}"
tar -xzf "${UPSTREAM_ARCHIVE}" -C "${WORK_DIR}"

POSTGRES_DIR="$(find "${WORK_DIR}" -mindepth 1 -maxdepth 1 -type d -name 'cw2_postgres_export_*' | sort | tail -n 1)"
UPSTREAM_DIR="$(find "${WORK_DIR}" -mindepth 1 -maxdepth 1 -type d -name 'cw2_upstream_export_*' | sort | tail -n 1)"

if [ -z "${POSTGRES_DIR}" ] || [ -z "${UPSTREAM_DIR}" ]; then
  echo "Unexpected bundle layout after extraction." >&2
  exit 1
fi

POSTGRES_DUMP="$(find "${POSTGRES_DIR}" -maxdepth 1 -type f -name '*.dump' | sort | head -n 1)"
MONGO_ARCHIVE="$(find "${UPSTREAM_DIR}/mongo" -maxdepth 1 -type f -name '*.archive.gz' | sort | head -n 1)"
MINIO_RAW_DIR="${UPSTREAM_DIR}/minio_raw/raw"

if [ ! -f "${POSTGRES_DUMP}" ] || [ ! -f "${MONGO_ARCHIVE}" ] || [ ! -d "${MINIO_RAW_DIR}" ]; then
  echo "Bundle contents are incomplete." >&2
  exit 1
fi

echo "Restoring PostgreSQL bundle into ${POSTGRES_CONTAINER} ..."
docker cp "${POSTGRES_DUMP}" "${POSTGRES_CONTAINER}:/tmp/reference.dump"
docker exec "${POSTGRES_CONTAINER}" sh -lc "psql -U postgres -d postgres -c \"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'fift' AND pid <> pg_backend_pid();\" >/dev/null"
docker exec "${POSTGRES_CONTAINER}" sh -lc "dropdb -U postgres --if-exists fift"
docker exec "${POSTGRES_CONTAINER}" sh -lc "createdb -U postgres fift"
docker exec "${POSTGRES_CONTAINER}" sh -lc "pg_restore -U postgres -d fift --clean --if-exists /tmp/reference.dump"
docker exec "${POSTGRES_CONTAINER}" sh -lc "rm -f /tmp/reference.dump"

echo "Restoring MongoDB bundle into ${MONGO_CONTAINER} ..."
docker cp "${MONGO_ARCHIVE}" "${MONGO_CONTAINER}:/tmp/reference.archive.gz"
docker exec "${MONGO_CONTAINER}" sh -lc "mongosh ift_cw --quiet --eval 'db.dropDatabase()'"
docker exec "${MONGO_CONTAINER}" sh -lc "mongorestore --gzip --archive=/tmp/reference.archive.gz --nsInclude=ift_cw.*"
docker exec "${MONGO_CONTAINER}" sh -lc "rm -f /tmp/reference.archive.gz"

echo "Restoring MinIO raw objects into ${MINIO_CLIENT_CONTAINER} ..."
docker exec "${MINIO_CLIENT_CONTAINER}" sh -lc "rm -rf /tmp/reference_raw && mkdir -p /tmp/reference_restore"
docker cp "${MINIO_RAW_DIR}" "${MINIO_CLIENT_CONTAINER}:/tmp/reference_restore/raw"
docker exec "${MINIO_CLIENT_CONTAINER}" sh -lc "MC_BIN=\$(command -v mc || echo /usr/bin/mc); \
  \"\$MC_BIN\" alias set ${MINIO_ALIAS} ${MINIO_ENDPOINT} ${MINIO_ACCESS_KEY} ${MINIO_SECRET_KEY} >/dev/null && \
  \"\$MC_BIN\" mb --ignore-existing ${MINIO_ALIAS}/${MINIO_BUCKET} >/dev/null && \
  \"\$MC_BIN\" rm -r --force ${MINIO_ALIAS}/${MINIO_BUCKET}/raw/source_a >/dev/null 2>&1 || true && \
  \"\$MC_BIN\" rm -r --force ${MINIO_ALIAS}/${MINIO_BUCKET}/raw/source_b >/dev/null 2>&1 || true && \
  \"\$MC_BIN\" mirror --overwrite /tmp/reference_restore/raw/source_a ${MINIO_ALIAS}/${MINIO_BUCKET}/raw/source_a && \
  \"\$MC_BIN\" mirror --overwrite /tmp/reference_restore/raw/source_b ${MINIO_ALIAS}/${MINIO_BUCKET}/raw/source_b && \
  rm -rf /tmp/reference_restore"

echo
echo "Frozen reproducibility bundle restored successfully."
echo "Next step:"
echo "  team_Pearson/coursework_one/.venv/bin/python team_Pearson/coursework_two/scripts/run_backtest_analysis_report.py --run-id 6905e84b-9e16-4106-8c0f-cd9ecce56728 --report-name cw2_formal_fund_ra3_s30_t50_20260420_report --cw2-config team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml"
