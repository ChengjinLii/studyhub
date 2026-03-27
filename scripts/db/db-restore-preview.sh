#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PRIVATE_DIR="${STUDYHUB_PRIVATE_DIR_PATH:-$ROOT_DIR/private}"
ENVIRONMENT="${STUDYHUB_ENVIRONMENT:-preview}"
INPUT_PATH="${1:-}"

if [[ -z "$INPUT_PATH" ]]; then
  echo "usage: bash scripts/db/db-restore-preview.sh /path/to/backup.sql.gz"
  exit 1
fi

if [[ "$ENVIRONMENT" == "production" ]]; then
  echo "production 环境禁止通过该脚本恢复数据库。"
  exit 1
fi

if [[ "${YES_PREVIEW_DB_RESTORE:-}" != "I_UNDERSTAND_RESTORE" ]]; then
  echo "恢复 preview 数据库需要显式设置 YES_PREVIEW_DB_RESTORE=I_UNDERSTAND_RESTORE"
  exit 1
fi

cd "$ROOT_DIR/backend"
export STUDYHUB_ENVIRONMENT="$ENVIRONMENT"
export STUDYHUB_PRIVATE_DIR_PATH="$PRIVATE_DIR"
"$ROOT_DIR/.venv/bin/python" -m app.ops.db_admin restore --input "$INPUT_PATH" --yes-preview-restore
