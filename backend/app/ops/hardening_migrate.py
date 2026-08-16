from __future__ import annotations

import argparse
import hashlib
import json
import os

from sqlalchemy import inspect, text

from app.core.config import get_settings
from app.core.db import get_engine
from app.models.finance import FinanceInstructionRecord
from app.models.materials import MaterialSecurityScanRecord
from app.ops.schema_audit import require_recent_nonempty_backup


MODULE_TABLES = {
    "finance-outbox": (FinanceInstructionRecord.__table__,),
    "material-security": (MaterialSecurityScanRecord.__table__,),
}
MODULE_DEFAULTS = {
    "finance-outbox": (
        ("finance_instructions", "status", "'PENDING'"),
        ("finance_instructions", "attempt_count", "0"),
    ),
    "material-security": (
        ("material_security_scans", "status", "'PENDING'"),
        ("material_security_scans", "release_status", "'VISIBLE'"),
        ("material_security_scans", "attempt_count", "0"),
    ),
}


def build_plan(module: str) -> dict[str, object]:
    tables = MODULE_TABLES.get(module)
    if tables is None:
        raise RuntimeError(f"unknown hardening migration module: {module}")
    engine = get_engine()
    existing = set(inspect(engine).get_table_names())
    create_tables = [table.name for table in tables if table.name not in existing]
    alter_defaults: list[dict[str, str]] = []
    inspector = inspect(engine)
    for table_name, column_name, default_sql in MODULE_DEFAULTS.get(module, ()):
        if table_name not in existing:
            continue
        columns = {str(item["name"]): item for item in inspector.get_columns(table_name)}
        actual_default = columns.get(column_name, {}).get("default")
        if actual_default is None:
            alter_defaults.append({"table": table_name, "column": column_name, "defaultSql": default_sql})
    canonical = json.dumps(
        {"module": module, "createTables": create_tables, "alterDefaults": alter_defaults},
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "module": module,
        "createTables": create_tables,
        "alterDefaults": alter_defaults,
        "planToken": hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16],
    }


def apply_plan(module: str, plan_token: str) -> dict[str, object]:
    settings = get_settings()
    if not settings.is_production:
        raise RuntimeError("hardening migration apply 只允许在 production 显式执行。")
    if os.getenv("YES_PRODUCTION_HARDENING_MIGRATION") != "I_UNDERSTAND_ADDITIVE_SCHEMA":
        raise RuntimeError("缺少 production additive hardening migration 确认变量。")
    plan = build_plan(module)
    if plan_token != plan["planToken"]:
        raise RuntimeError("plan token 不匹配，数据库状态已变化。")
    backup = require_recent_nonempty_backup(settings.private_dir, "production", max_age_seconds=120 * 60)
    tables = MODULE_TABLES[module]
    engine = get_engine()
    for table in tables:
        if table.name in plan["createTables"]:
            table.create(bind=engine, checkfirst=True)
    with engine.begin() as connection:
        for item in plan["alterDefaults"]:
            connection.execute(
                text(
                    f"ALTER TABLE `{item['table']}` ALTER COLUMN `{item['column']}` "
                    f"SET DEFAULT {item['defaultSql']}"
                )
            )
    after = build_plan(module)
    if after["createTables"] or after["alterDefaults"]:
        raise RuntimeError(f"hardening migration 验收失败：{after}")
    return {
        "module": module,
        "createdTables": plan["createTables"],
        "alteredDefaults": plan["alterDefaults"],
        "backupFile": str(backup),
        "verified": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="StudyHub protected additive hardening migrations")
    parser.add_argument("command", choices=("plan", "apply"))
    parser.add_argument("module", choices=tuple(MODULE_TABLES))
    parser.add_argument("--plan-token", default="")
    args = parser.parse_args()
    payload = build_plan(args.module) if args.command == "plan" else apply_plan(args.module, args.plan_token)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
