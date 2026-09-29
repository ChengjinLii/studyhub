#!/usr/bin/env bash
set -euo pipefail

RUNTIME_ROOT="${STUDYHUB_RELEASE_ROOT:-/data/studyhub-runtime}"
MIN_AGE_DAYS="${STUDYHUB_STALE_RELEASE_MIN_AGE_DAYS:-7}"
MODE="${1:---dry-run}"

if [[ "$MODE" != "--dry-run" && "$MODE" != "--apply" ]]; then
  echo "usage: bash scripts/deploy/cleanup-stale-releases.sh [--dry-run|--apply]"
  exit 2
fi
if ! [[ "$MIN_AGE_DAYS" =~ ^[1-9][0-9]*$ ]]; then
  echo "STUDYHUB_STALE_RELEASE_MIN_AGE_DAYS must be a positive integer"
  exit 2
fi
if [[ ! -d "$RUNTIME_ROOT" ]]; then
  echo "release root not found: $RUNTIME_ROOT"
  exit 0
fi

CURRENT="$(readlink -f "$RUNTIME_ROOT/current" 2>/dev/null || true)"
candidate_in_use() {
  local candidate="$1"
  local link target
  for link in /proc/[0-9]*/cwd /proc/[0-9]*/exe /proc/[0-9]*/root; do
    target="$(readlink -f "$link" 2>/dev/null || true)"
    if [[ "$target" == "$candidate" || "$target" == "$candidate/"* ]]; then
      return 0
    fi
  done
  return 1
}

found=0
reclaimed_kb=0
while IFS= read -r -d '' candidate; do
  basename="$(basename "$candidate")"
  if ! [[ "$basename" =~ ^interrupted-[0-9a-f]{12}$ ]]; then
    continue
  fi
  canonical="$(readlink -f "$candidate")"
  if [[ "$canonical" != "$RUNTIME_ROOT/"* || "$canonical" == "$CURRENT" ]]; then
    echo "skip protected path: $candidate"
    continue
  fi
  if candidate_in_use "$canonical"; then
    echo "skip path used by a running process: $candidate"
    continue
  fi
  size_kb="$(du -sk --one-file-system "$candidate" | awk '{print $1}')"
  found=$((found + 1))
  reclaimed_kb=$((reclaimed_kb + size_kb))
  if [[ "$MODE" == "--apply" ]]; then
    rm -rf --one-file-system "$candidate"
    echo "removed stale interrupted release: $candidate (${size_kb} KiB)"
  else
    echo "would remove stale interrupted release: $candidate (${size_kb} KiB)"
  fi
done < <(find "$RUNTIME_ROOT" -mindepth 1 -maxdepth 1 -type d -name 'interrupted-*' -mtime "+$MIN_AGE_DAYS" -print0)

if (( found == 0 )); then
  echo "no stale interrupted releases found"
elif [[ "$MODE" == "--dry-run" ]]; then
  echo "dry run: $found candidate(s), approximately $reclaimed_kb KiB reclaimable"
else
  echo "cleanup complete: $found candidate(s), approximately $reclaimed_kb KiB reclaimed"
fi
