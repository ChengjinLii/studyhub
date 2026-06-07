#!/usr/bin/env bash
set -euo pipefail

BACKEND_SERVICE="${STUDYHUB_BACKEND_SERVICE:-studyhub-backend.service}"
LOG_SINCE="${STUDYHUB_P0_LOG_SINCE:-30 minutes ago}"
PATTERNS=(
  "Unknown column 'market_items.source'"
  "Unknown column 'orders.uploader_id'"
)

if ! command -v journalctl >/dev/null 2>&1; then
  echo "journalctl is not available"
  exit 2
fi

log_file="$(mktemp)"
trap 'rm -f "$log_file"' EXIT

journalctl -u "$BACKEND_SERVICE" --since "$LOG_SINCE" --no-pager >"$log_file"

found=0
for pattern in "${PATTERNS[@]}"; do
  if grep -F -- "$pattern" "$log_file" >/dev/null; then
    echo "found recent schema drift log: $pattern"
    grep -F -- "$pattern" "$log_file" | tail -5
    found=1
  fi
done

if [[ "$found" == "1" ]]; then
  exit 2
fi

echo "No P0 schema drift logs found for $BACKEND_SERVICE since $LOG_SINCE."
