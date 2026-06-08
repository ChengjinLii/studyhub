#!/usr/bin/env bash
set -euo pipefail

BACKEND_SERVICE="${STUDYHUB_BACKEND_SERVICE:-studyhub-backend.service}"
WORKER_SERVICE="${STUDYHUB_WORKER_SERVICE:-studyhub-worker.service}"
LOG_SERVICES="${STUDYHUB_P0_LOG_SERVICES:-$BACKEND_SERVICE $WORKER_SERVICE}"
LOG_SINCE="${STUDYHUB_P0_LOG_SINCE:-30 minutes ago}"
PATTERNS=(
  "Unknown column 'market_items.source'"
  "Unknown column 'orders.uploader_id'"
)

if ! command -v journalctl >/dev/null 2>&1; then
  echo "journalctl is not available"
  exit 2
fi

if [[ -z "${LOG_SERVICES//[[:space:]]/}" ]]; then
  echo "STUDYHUB_P0_LOG_SERVICES must contain at least one systemd service name"
  exit 2
fi

log_file="$(mktemp)"
trap 'rm -f "$log_file"' EXIT

found=0
for service in $LOG_SERVICES; do
  journalctl -u "$service" --since "$LOG_SINCE" --no-pager >"$log_file"
  for pattern in "${PATTERNS[@]}"; do
    if grep -F -- "$pattern" "$log_file" >/dev/null; then
      echo "found recent schema drift log in $service: $pattern"
      grep -F -- "$pattern" "$log_file" | tail -5
      found=1
    fi
  done
done

if [[ "$found" == "1" ]]; then
  exit 2
fi

echo "No P0 schema drift logs found for services [$LOG_SERVICES] since $LOG_SINCE."
