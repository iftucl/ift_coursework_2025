#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COURSEWORK_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

CRON_SCHEDULE="${CRON_SCHEDULE:-5 6 * * *}"
MARKER="# cw1-auto-update"
LOG_PATH="$COURSEWORK_DIR/logs/auto_update.log"
JOB_CMD="/bin/zsh $SCRIPT_DIR/auto_update_job.sh >> $LOG_PATH 2>&1"
ENTRY="$CRON_SCHEDULE $JOB_CMD $MARKER"

mkdir -p "$COURSEWORK_DIR/logs"

EXISTING="$(crontab -l 2>/dev/null || true)"
UPDATED="$(printf "%s\n" "$EXISTING" | grep -v "cw1-auto-update" || true)"
{
  printf "%s\n" "$UPDATED"
  printf "%s\n" "$ENTRY"
} | sed '/^[[:space:]]*$/d' | crontab -

echo "Installed cron entry:"
echo "$ENTRY"
echo "Note: cron schedule is interpreted in host local timezone."
