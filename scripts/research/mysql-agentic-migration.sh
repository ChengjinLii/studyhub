#!/usr/bin/env bash
set -euo pipefail

# Runs the complete Alembic chain against the MySQL URL supplied by CI, then
# inspects the additive Agentic governance columns.  This avoids treating a
# SQLite fixture migration as proof of production dialect compatibility.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
PYTHON_BIN="${STUDYHUB_PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

fail() {
  printf 'mysql-agentic-migration: %s\n' "$*" >&2
  exit 1
}

[[ -n "${STUDYHUB_DATABASE_URL:-}" ]] || fail "STUDYHUB_DATABASE_URL is required"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v "$PYTHON_BIN" 2>/dev/null || true)"
fi
[[ -n "$PYTHON_BIN" && -x "$PYTHON_BIN" ]] || fail "missing Python interpreter"

cd "$BACKEND_DIR"
"$PYTHON_BIN" -m alembic -c alembic.ini upgrade head
"$PYTHON_BIN" - <<'PY'
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
