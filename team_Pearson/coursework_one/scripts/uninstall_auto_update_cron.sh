#!/bin/zsh
set -euo pipefail

EXISTING="$(crontab -l 2>/dev/null || true)"
UPDATED="$(printf "%s\n" "$EXISTING" | grep -v "cw1-auto-update" || true)"
printf "%s\n" "$UPDATED" | sed '/^[[:space:]]*$/d' | crontab -

echo "Removed cron entries tagged with cw1-auto-update."

