#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_COUNT=0

while IFS= read -r -d '' script_path; do
  bash -n "$script_path"
  SCRIPT_COUNT=$((SCRIPT_COUNT + 1))
done < <(find "$ROOT_DIR/scripts" -type f -name '*.sh' -print0 | sort -z)

echo "Shell script syntax check passed ($SCRIPT_COUNT scripts)."
