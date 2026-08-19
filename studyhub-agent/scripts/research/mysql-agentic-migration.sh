#!/usr/bin/env bash
set -euo pipefail

# Runs the complete Alembic chain against the MySQL URL supplied by CI, then
# inspects the additive schema guarantees covered by this gate. This avoids
# treating a SQLite fixture migration as proof of production compatibility.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKSPACE_ROOT="$(cd "$ROOT_DIR/.." && pwd)"
BACKEND_DIR="$WORKSPACE_ROOT/backend"
PYTHON_BIN="${STUDYHUB_PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
MYSQL_MIGRATION_LOG=""

fail() {
  printf 'mysql-agentic-migration: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  if [[ -n "$MYSQL_MIGRATION_LOG" && -f "$MYSQL_MIGRATION_LOG" ]]; then
    rm -f "$MYSQL_MIGRATION_LOG"
  fi
}

sanitize_log() {
  # Never place a database password in an Actions annotation.  SQLAlchemy and
  # driver errors normally avoid echoing the URL, but this remains a safe
  # boundary if that behavior changes in a later dependency release.
  sed -E 's#(mysql\+[[:alnum:]_+-]+://)[^@[:space:]]+@#\1***@#g' "$1"
}

run_stage() {
  local stage="$1"
  shift

  MYSQL_MIGRATION_LOG="$(mktemp "${TMPDIR:-/tmp}/studyhub-mysql-migration.XXXXXX")"
  if "$@" >"$MYSQL_MIGRATION_LOG" 2>&1; then
    sanitize_log "$MYSQL_MIGRATION_LOG"
    cleanup
    MYSQL_MIGRATION_LOG=""
    return 0
  else
    local status=$?
    local detail
    detail="$(sanitize_log "$MYSQL_MIGRATION_LOG" | tail -n 16 | tr '\n' ' ' | tr -s ' ')"
    printf 'mysql-agentic-migration: %s failed (exit %s)\n' "$stage" "$status" >&2
    printf '::error title=MySQL Agentic migration failed::stage=%s; %s\n' "$stage" "$detail" >&2
    cleanup
    MYSQL_MIGRATION_LOG=""
    return "$status"
  fi
}

trap cleanup EXIT

[[ -n "${STUDYHUB_DATABASE_URL:-}" ]] || fail "STUDYHUB_DATABASE_URL is required"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v "$PYTHON_BIN" 2>/dev/null || true)"
fi
[[ -n "$PYTHON_BIN" && -x "$PYTHON_BIN" ]] || fail "missing Python interpreter"

cd "$BACKEND_DIR"
run_stage "database connectivity" "$PYTHON_BIN" - <<'PY'
import os

import sqlalchemy as sa

url = os.environ["STUDYHUB_DATABASE_URL"]
engine = sa.create_engine(url, future=True)
try:
    with engine.connect() as connection:
        version = connection.execute(sa.text("SELECT VERSION()")).scalar_one()
    print("MySQL connectivity verified:", version)
finally:
    engine.dispose()
PY
run_stage "Alembic upgrade" "$PYTHON_BIN" -m alembic -c alembic.ini upgrade head
run_stage "schema inspection" "$PYTHON_BIN" - <<'PY'
import os

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

url = os.environ["STUDYHUB_DATABASE_URL"]
engine = sa.create_engine(url, future=True)
required = {
    "agent_artifacts": {
        "training_allowed",
        "sensitivity",
        "license_class",
        "source_scope",
        "contains_personal_data",
        "anonymization_version",
        "retention_policy",
    },
    "agent_steps": {"state_group_key_v2"},
    "materials": {"submission_key"},
}
try:
    inspector = sa.inspect(engine)
    missing = {
        table: sorted(columns - {column["name"] for column in inspector.get_columns(table)})
        for table, columns in required.items()
    }
    missing = {table: columns for table, columns in missing.items() if columns}
    if missing:
        raise SystemExit(f"missing migration columns: {missing}")
    material_indexes = {
        index["name"]: index
        for index in inspector.get_indexes("materials")
    }
    submission_index = material_indexes.get("uq_materials_uploader_submission_key")
    if not submission_index or not submission_index.get("unique"):
        raise SystemExit("missing unique material submission idempotency index")
    if submission_index.get("column_names") != ["uploader_id", "submission_key"]:
        raise SystemExit(f"unexpected material submission index: {submission_index}")
    with engine.connect() as connection:
        revision = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
    expected_revision = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    if revision != expected_revision:
        raise SystemExit(f"unexpected Alembic revision: {revision}")
    print("MySQL Agentic migration verified at revision", revision)
finally:
    engine.dispose()
PY
