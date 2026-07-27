#!/usr/bin/env bash
set -euo pipefail

# Runs the complete Alembic chain against the MySQL URL supplied by CI, then
# inspects the additive Agentic governance columns.  This avoids treating a
# SQLite fixture migration as proof of production dialect compatibility.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
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
}
try:
    inspector = sa.inspect(engine)
    missing = {
        table: sorted(columns - {column["name"] for column in inspector.get_columns(table)})
        for table, columns in required.items()
    }
    missing = {table: columns for table, columns in missing.items() if columns}
    if missing:
        raise SystemExit(f"missing Agentic migration columns: {missing}")
    with engine.connect() as connection:
        revision = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
    if revision != "0007_add_agentic_data_governance":
        raise SystemExit(f"unexpected Alembic revision: {revision}")
    print("MySQL Agentic migration verified at revision", revision)
finally:
    engine.dispose()
PY
