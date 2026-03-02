#!/bin/sh
set -eu

RUN_DATE="${1:-}"
SYMBOL="${2:-AAPL}"

if [ -z "$RUN_DATE" ]; then
  echo "Usage: ./scripts/verify_minio.sh <RUN_DATE:YYYY-MM-DD> [SYMBOL]"
  exit 1
fi

YEAR="$(printf '%s' "$RUN_DATE" | cut -d- -f1)"
MONTH="$(printf '%s' "$RUN_DATE" | cut -d- -f2)"

docker exec -i minio_client_cw sh -lc '
MC_BIN="$(command -v mc || echo /usr/bin/mc)";
if [ ! -x "$MC_BIN" ]; then
  echo "mc binary not found in container (PATH or /usr/bin/mc)";
  exit 2;
fi;

"$MC_BIN" alias set cw http://miniocw:9000 ift_bigdata minio_password >/dev/null &&
echo "source_a_count=$("$MC_BIN" ls --recursive cw/csreport/raw/source_a/pricing_fundamentals/run_date='"$RUN_DATE"'/ | wc -l)" &&
echo "source_b_count=$("$MC_BIN" ls --recursive cw/csreport/raw/source_b/news/run_date='"$RUN_DATE"'/ | wc -l)" &&
echo "source_b_month_objects (run_date='"$RUN_DATE"', year='"$YEAR"', month='"$MONTH"'):" &&
"$MC_BIN" ls --recursive cw/csreport/raw/source_b/news/run_date='"$RUN_DATE"'/year='"$YEAR"'/month='"$MONTH"'/ || true &&
echo "sample_head (symbol='"$SYMBOL"'):" &&
SAMPLE_KEY="cw/csreport/raw/source_b/news/run_date='"$RUN_DATE"'/year='"$YEAR"'/month='"$MONTH"'/symbol='"$SYMBOL"'.jsonl" &&
if "$MC_BIN" stat "$SAMPLE_KEY" >/dev/null 2>&1; then
  "$MC_BIN" cat "$SAMPLE_KEY" | head -n 5;
else
  echo "sample object not found for symbol='"$SYMBOL"' under month='"$MONTH"'";
fi
'
