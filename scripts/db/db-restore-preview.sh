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

if [[ -z "${INPUT_PATH//[[:space:]]/}" ]]; then
  echo "backup input path must not be whitespace only"
  exit 2
fi

if [[ "$INPUT_PATH" != /* ]]; then
  INPUT_PATH="$ROOT_DIR/$INPUT_PATH"
fi

if [[ "$ENVIRONMENT" != "preview" ]]; then
  echo "db-restore-preview.sh is preview-only; got STUDYHUB_ENVIRONMENT=$ENVIRONMENT"
  exit 2
fi

if [[ ! -f "$PRIVATE_DIR/.env.preview" ]]; then
  echo "missing preview env file: $PRIVATE_DIR/.env.preview"
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
