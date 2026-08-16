from __future__ import annotations

import argparse
import hashlib
import json
import os
import re

from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_engine
from app.ops.schema_audit import build_schema_audit_payload, require_recent_nonempty_backup


IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _select_indexes(payload: dict[str, object], scopes: list[str]) -> list[dict[str, object]]:
    indexes = list(payload.get("missingIndexes") or [])
    if not scopes:
        return indexes
    requested: set[tuple[str, str]] = set()
    for scope in scopes:
        if scope.count(".") != 1:
            raise RuntimeError(f"--only 需要 table.index 格式：{scope}")
        table, index = scope.split(".", 1)
        if not IDENTIFIER.fullmatch(table) or not IDENTIFIER.fullmatch(index):
            raise RuntimeError(f"--only 包含无效标识符：{scope}")
        requested.add((table, index))
    existing = {(str(item["table"]), str(item["index"])) for item in indexes}
    unknown = sorted(requested - existing)
    if unknown:
        rendered = ", ".join(f"{table}.{index}" for table, index in unknown)
        raise RuntimeError(f"请求的索引不在当前缺失清单中（可能已创建）：{rendered}")
    return [item for item in indexes if (str(item["table"]), str(item["index"])) in requested]


def _plan_token(indexes: list[dict[str, object]]) -> str:
    canonical = json.dumps(indexes, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def build_plan(scopes: list[str]) -> dict[str, object]:
    indexes = _select_indexes(build_schema_audit_payload(), scopes)
    return {"indexCount": len(indexes), "indexes": indexes, "planToken": _plan_token(indexes)}


def apply_plan(scopes: list[str], token: str) -> dict[str, object]:
    settings = get_settings()
    if not settings.is_production:
        raise RuntimeError("索引执行器当前只用于受保护的 production 收敛。")
    if os.getenv("YES_PRODUCTION_CREATE_INDEXES") != "I_UNDERSTAND_CREATE_INDEXES":
        raise RuntimeError("缺少 production 索引迁移确认变量。")
    if not scopes:
        raise RuntimeError("production 创建索引必须显式传入 --only，禁止全量执行。")
    plan = build_plan(scopes)
    if not plan["indexes"]:
        raise RuntimeError("没有需要创建的索引。")
    if token != plan["planToken"]:
        raise RuntimeError("plan token 不匹配，数据库状态或执行范围已变化。")
    backup = require_recent_nonempty_backup(settings.private_dir, "production", max_age_seconds=120 * 60)
    with get_engine().begin() as connection:
        for item in plan["indexes"]:
            sql = str(item["sql"])
            if not re.fullmatch(
                r"CREATE INDEX `[A-Za-z_][A-Za-z0-9_]*` ON `[A-Za-z_][A-Za-z0-9_]*` \(`(?:[A-Za-z_][A-Za-z0-9_]*`(?:, )?)+\);",
                sql,
            ):
                raise RuntimeError(f"拒绝执行非白名单 CREATE INDEX：{sql}")
            connection.execute(text(sql))
    return {"created": [f"{item['table']}.{item['index']}" for item in plan["indexes"]], "backupFile": str(backup)}


def main() -> int:
    parser = argparse.ArgumentParser(description="StudyHub protected production index migration")
    parser.add_argument("command", choices=("plan", "apply"))
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--plan-token", default="")
    args = parser.parse_args()
    payload = build_plan(args.only) if args.command == "plan" else apply_plan(args.only, args.plan_token)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
