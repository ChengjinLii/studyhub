from __future__ import annotations

import argparse
from datetime import UTC, datetime
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import BinaryIO

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url

from app.core.config import Settings, get_settings
from app.core.db import (
    check_database,
    ensure_database_schema_ready,
    expected_table_names,
    initialize_database,
    list_missing_tables,
    reset_database_runtime,
)
from app.ops.schema_audit import (
    assert_additive_sql,
    build_schema_audit_payload,
    build_scoped_additive_migration_payload,
    find_latest_nonempty_backup,
)


def _masked_database_url(url: URL) -> str:
    return str(url.render_as_string(hide_password=True))


def _require_mysql_url(settings: Settings) -> URL:
    url = make_url(settings.resolved_database_url)
    backend = url.get_backend_name().lower()
    if backend != "mysql":
        raise RuntimeError(f"当前数据库不是 MySQL：{_masked_database_url(url)}")
    if not url.database:
        raise RuntimeError("数据库连接缺少 database 名称。")
    return url


def _mysql_command_prefix(url: URL) -> tuple[list[str], dict[str, str]]:
    host = url.host or "127.0.0.1"
    port = str(url.port or 3306)
    username = url.username or ""
    env = {}
    if url.password:
        env["MYSQL_PWD"] = url.password
    return ["-h", host, "-P", port, "-u", username, url.database or ""], env


def _default_backup_path(settings: Settings) -> Path:
    root = settings.private_dir / "backups" / settings.environment
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return root / f"studyhub-{settings.environment}-{timestamp}.sql.gz"


def _ensure_sqlite_parent_dir(settings: Settings) -> None:
    if settings.database_is_sqlite:
        sqlite_path = Path(settings.resolved_database_url.removeprefix("sqlite+pysqlite:///"))
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)


def command_describe(settings: Settings) -> int:
    url = make_url(settings.resolved_database_url)
    payload = {
        "environment": settings.environment,
        "databaseUrl": _masked_database_url(url),
        "databaseAutoCreate": settings.should_auto_create_database,
        "expectedTableCount": len(expected_table_names()),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_check(settings: Settings) -> int:
    _ensure_sqlite_parent_dir(settings)
    check_database()
    missing_tables = list_missing_tables()
    payload = {
        "environment": settings.environment,
        "databaseUrl": _masked_database_url(make_url(settings.resolved_database_url)),
        "missingTables": missing_tables,
        "ready": not missing_tables,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not missing_tables else 2


def command_check_schema(settings: Settings) -> int:
    _ensure_sqlite_parent_dir(settings)
    check_database()
    payload = build_schema_audit_payload()
    payload.update(
        {
            "environment": settings.environment,
            "databaseUrl": _masked_database_url(make_url(settings.resolved_database_url)),
        }
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ready"] else 2


def command_init_schema(settings: Settings, *, allow_preview: bool) -> int:
    _ensure_sqlite_parent_dir(settings)
    if settings.is_production:
        raise RuntimeError("production 模式禁止通过 db_admin init-schema 自动建表。")
    if settings.is_preview and not allow_preview:
        raise RuntimeError("preview 建表需要显式传入 --allow-preview-create。")
    initialize_database()
    ensure_database_schema_ready()
    print(
        json.dumps(
            {
                "environment": settings.environment,
                "initialized": True,
                "expectedTableCount": len(expected_table_names()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_backup(settings: Settings, *, output: Path | None) -> int:
    url = _require_mysql_url(settings)
    target = output or _default_backup_path(settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    mysqldump = shutil.which("mysqldump")
    if not mysqldump:
        raise RuntimeError("未找到 mysqldump，请先安装 MySQL 客户端。")

    command_suffix, password_env = _mysql_command_prefix(url)
    command = [
        mysqldump,
        "--single-transaction",
        "--quick",
        "--routines",
        "--triggers",
        "--set-gtid-purged=OFF",
        "--default-character-set=utf8mb4",
        *command_suffix,
    ]
    process_env = None
    if password_env:
        process_env = {**os.environ, **password_env}
    with target.open("wb") as raw_file:
        sink: BinaryIO
        if target.suffix == ".gz":
            sink = gzip.GzipFile(fileobj=raw_file, mode="wb")
        else:
            sink = raw_file
        try:
            with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=process_env) as process:
                assert process.stdout is not None
                assert process.stderr is not None
                shutil.copyfileobj(process.stdout, sink)
                stderr = process.stderr.read().decode("utf-8", errors="replace")
                return_code = process.wait()
                if return_code != 0:
                    raise RuntimeError(f"mysqldump 失败：{stderr.strip() or f'退出码 {return_code}'}")
        finally:
            if sink is not raw_file:
                sink.close()
    print(
        json.dumps(
            {
                "environment": settings.environment,
                "backupFile": str(target),
                "databaseUrl": _masked_database_url(url),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _parse_only_columns(values: list[str]) -> set[tuple[str, str]] | None:
    if not values:
        return None
    parsed: set[tuple[str, str]] = set()
    for value in values:
        raw = value.strip()
        if raw.count(".") != 1:
            raise RuntimeError(f"--only 需要使用 table.column 格式：{value}")
        table, column = raw.split(".", 1)
        table = table.strip()
        column = column.strip()
        if not table or not column:
            raise RuntimeError(f"--only 需要使用 table.column 格式：{value}")
        parsed.add((table, column))
    return parsed


def command_migrate_additive(settings: Settings, *, plan: bool, yes: bool, only: list[str] | None = None) -> int:
    if plan == yes:
        raise RuntimeError("migrate-additive 必须且只能传入 --plan 或 --yes。")

    _ensure_sqlite_parent_dir(settings)
    check_database()
    only_columns = _parse_only_columns(only or [])
    payload = build_scoped_additive_migration_payload(only_columns=only_columns)
    payload.update(
        {
            "environment": settings.environment,
            "databaseUrl": _masked_database_url(make_url(settings.resolved_database_url)),
            "mode": "plan" if plan else "execute",
        }
    )
    statements = list(payload["additiveStatements"])
    for sql in statements:
        assert_additive_sql(sql)

    if plan:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["executable"] else 2

    if settings.is_production:
        backup_file = find_latest_nonempty_backup(settings.private_dir, settings.environment)
        if backup_file is None:
            raise RuntimeError("production migrate-additive --yes 需要先完成非空数据库备份。")
        payload["backupFile"] = str(backup_file)

    if not payload["executable"]:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2

    if statements:
        from app.core.db import get_engine

        engine = get_engine()
        with engine.begin() as connection:
            for sql in statements:
                connection.execute(text(sql.rstrip(";")))

    after = build_schema_audit_payload()
    payload["executedStatements"] = statements
    payload["after"] = after
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if only_columns:
        missing_after = {
            (item["table"], item["column"])
            for item in after["missingColumns"]
        }
        return 0 if not (missing_after & only_columns) else 2
    return 0 if after["ready"] else 2


def command_restore(settings: Settings, *, input_path: Path, yes_preview_restore: bool) -> int:
    if settings.is_production:
        raise RuntimeError("production 模式禁止通过 db_admin restore 执行恢复。")
    if settings.is_preview and not yes_preview_restore:
        raise RuntimeError("preview 恢复需要显式传入 --yes-preview-restore。")
    url = _require_mysql_url(settings)
    if not input_path.exists():
        raise RuntimeError(f"备份文件不存在：{input_path}")
    mysql = shutil.which("mysql")
    if not mysql:
        raise RuntimeError("未找到 mysql 客户端，请先安装 MySQL 客户端。")

    command_suffix, password_env = _mysql_command_prefix(url)
    command = [mysql, "--default-character-set=utf8mb4", *command_suffix]
    open_input = gzip.open if input_path.suffix == ".gz" else open
    process_env = None
    if password_env:
        process_env = {**os.environ, **password_env}
    with open_input(input_path, "rb") as source, subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=process_env,
    ) as process:
        assert process.stdin is not None
        assert process.stderr is not None
        shutil.copyfileobj(source, process.stdin)
        process.stdin.close()
        stderr = process.stderr.read().decode("utf-8", errors="replace")
        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(f"mysql restore 失败：{stderr.strip() or f'退出码 {return_code}'}")

    print(
        json.dumps(
            {
                "environment": settings.environment,
                "restoredFrom": str(input_path),
                "databaseUrl": _masked_database_url(url),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="StudyHub FastAPI database admin helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("describe")
    subparsers.add_parser("check")
    subparsers.add_parser("check-schema")

    init_parser = subparsers.add_parser("init-schema")
    init_parser.add_argument("--allow-preview-create", action="store_true")

    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--output", type=Path)

    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--input", type=Path, required=True)
    restore_parser.add_argument("--yes-preview-restore", action="store_true")

    migrate_parser = subparsers.add_parser("migrate-additive")
    migrate_mode = migrate_parser.add_mutually_exclusive_group(required=True)
    migrate_mode.add_argument("--plan", action="store_true")
    migrate_mode.add_argument("--yes", action="store_true")
    migrate_parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="TABLE.COLUMN",
        help="limit the additive plan to a confirmed missing column; may be repeated",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = get_settings()
    reset_database_runtime()

    if args.command == "describe":
        return command_describe(settings)
    if args.command == "check":
        return command_check(settings)
    if args.command == "check-schema":
        return command_check_schema(settings)
    if args.command == "init-schema":
        return command_init_schema(settings, allow_preview=bool(args.allow_preview_create))
    if args.command == "backup":
        return command_backup(settings, output=args.output)
    if args.command == "restore":
        return command_restore(
            settings,
            input_path=args.input,
            yes_preview_restore=bool(args.yes_preview_restore),
        )
    if args.command == "migrate-additive":
        return command_migrate_additive(settings, plan=bool(args.plan), yes=bool(args.yes), only=list(args.only))
    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
