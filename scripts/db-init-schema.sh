#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PRIVATE_DIR="${STUDYHUB_PRIVATE_DIR_PATH:-$ROOT_DIR/private}"
ENVIRONMENT="${STUDYHUB_ENVIRONMENT:-preview}"

if [[ "$ENVIRONMENT" == "production" ]]; then
  echo "production 环境禁止通过该脚本自动建表。"
  exit 1
fi

if [[ "$ENVIRONMENT" == "preview" && "${ALLOW_PREVIEW_DB_CREATE:-}" != "I_UNDERSTAND_CREATE_SCHEMA" ]]; then
  echo "preview 建表需要显式设置 ALLOW_PREVIEW_DB_CREATE=I_UNDERSTAND_CREATE_SCHEMA"
  exit 1
fi

cd "$ROOT_DIR/backend"
export STUDYHUB_ENVIRONMENT="$ENVIRONMENT"
export STUDYHUB_PRIVATE_DIR_PATH="$PRIVATE_DIR"
"$ROOT_DIR/.venv/bin/python" -m app.ops.db_admin init-schema --allow-preview-create
