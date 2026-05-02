#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CW2_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEAM_ROOT="$(cd "${CW2_ROOT}/.." && pwd)"
CW1_ROOT="${TEAM_ROOT}/coursework_one"

POETRY_BIN="${POETRY_BIN:-poetry}"
RUN_SAFETY=0
RUN_SECURITY=1
RUN_TESTS=1
RUN_DOCS=0
HTML_COVERAGE=0

usage() {
  cat <<'EOF'
Usage:
  team_Pearson/coursework_two/scripts/run_quality_checks.sh [options]

Runs the CW2 quality gate through the shared CW1 Poetry environment.

Options:
  --html-coverage      Add an HTML coverage report under coursework_two/htmlcov
  --docs               Build the shared CW1+CW2 Sphinx documentation site
  --with-safety        Add Safety dependency scan for the shared Poetry env
  --skip-safety        Explicitly skip dependency vulnerability scan
  --skip-security      Skip Bandit security scan
  --skip-tests         Skip pytest coverage checks
  -h, --help           Show this help message

Environment:
  POETRY_BIN           Poetry executable to use. Defaults to "poetry".
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --html-coverage)
      HTML_COVERAGE=1
      shift
      ;;
    --docs)
      RUN_DOCS=1
      shift
      ;;
    --with-safety)
      RUN_SAFETY=1
      shift
      ;;
    --skip-safety)
      RUN_SAFETY=0
      shift
      ;;
    --skip-security)
      RUN_SECURITY=0
      shift
      ;;
    --skip-tests)
      RUN_TESTS=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

require_file() {
  if [ ! -e "$1" ]; then
    echo "Required path not found: $1" >&2
    exit 1
  fi
}

run_step() {
  local label="$1"
  shift
  echo
  echo "==> ${label}"
  "$@"
}

require_file "${CW1_ROOT}/pyproject.toml"
require_file "${CW2_ROOT}/pytest.ini"

cd "${CW1_ROOT}"

CW2_MAIN="../coursework_two/Main.py"
CW2_MODULES="../coursework_two/modules"
CW2_SCRIPTS="../coursework_two/scripts"
CW2_TESTS="../coursework_two/tests"

run_step "poetry project check" \
  "${POETRY_BIN}" check

run_step "black format check" \
  "${POETRY_BIN}" run black --check --line-length 100 \
    "${CW2_MAIN}" "${CW2_MODULES}" "${CW2_SCRIPTS}" "${CW2_TESTS}"

run_step "isort import-order check" \
  "${POETRY_BIN}" run isort --check --profile black --line-length 100 \
    "${CW2_MAIN}" "${CW2_MODULES}" "${CW2_SCRIPTS}" "${CW2_TESTS}"

run_step "flake8 lint check" \
  "${POETRY_BIN}" run flake8 "${CW2_MAIN}" "${CW2_MODULES}" "${CW2_SCRIPTS}"

if [ "${RUN_SECURITY}" -eq 1 ]; then
  run_step "bandit security scan" \
    "${POETRY_BIN}" run bandit -r "${CW2_MODULES}" "${CW2_SCRIPTS}" -ll -c ../coursework_two/bandit.yaml
fi

if [ "${RUN_SAFETY}" -eq 1 ]; then
  run_step "safety dependency scan" \
    "${POETRY_BIN}" run safety check
fi

if [ "${RUN_TESTS}" -eq 1 ]; then
  PYTEST_ARGS=(-c ../coursework_two/pytest.ini ../coursework_two/tests/)
  if [ "${HTML_COVERAGE}" -eq 1 ]; then
    PYTEST_ARGS+=(--cov-report=html:../coursework_two/htmlcov)
  fi
  run_step "pytest coverage gate" \
    "${POETRY_BIN}" run pytest "${PYTEST_ARGS[@]}"
fi

if [ "${RUN_DOCS}" -eq 1 ]; then
  run_step "sphinx documentation build" \
    "${POETRY_BIN}" run python scripts/build_sphinx_docs.py --clean
fi

echo
echo "CW2 quality checks completed."
