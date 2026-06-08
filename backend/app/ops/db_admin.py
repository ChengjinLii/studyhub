from __future__ import annotations

import argparse
from datetime import UTC, datetime
import gzip
import hashlib
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
    build_scoped_schema_audit_payload,
    build_scoped_additive_migration_payload,
    require_recent_nonempty_backup,
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


def _validate_backup_file(path: Path) -> int:
    if not path.exists() or not path.is_file():
        raise RuntimeError(f"备份文件未生成：{path}")
    size_bytes = path.stat().st_size
    if size_bytes <= 0:
        raise RuntimeError(f"备份文件为空：{path}")
    if path.suffix == ".gz":
        try:
            with gzip.open(path, "rb") as source:
                while source.read(1024 * 1024):
                    pass
        except OSError as exc:
            raise RuntimeError(f"备份 gzip 校验失败：{path}: {exc}") from exc
    return size_bytes


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_backup_target_available(path: Path) -> None:
    if path.exists():
        raise RuntimeError(f"备份目标已存在，拒绝覆盖：{path}")


def _temporary_backup_path(target: Path) -> Path:
    suffix = target.suffix
    stem = target.name[: -len(suffix)] if suffix else target.name
    return target.with_name(f".{stem}.tmp-{os.getpid()}{suffix}")


def _publish_backup_file(temp_target: Path, target: Path) -> None:
    try:
        os.link(temp_target, target)
    except FileExistsError as exc:
        raise RuntimeError(f"备份目标已存在，拒绝覆盖：{target}") from exc
    temp_target.unlink(missing_ok=True)


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


def command_check_schema(settings: Settings, *, only: list[str] | None = None) -> int:
    _ensure_sqlite_parent_dir(settings)
    check_database()
    only_columns = _parse_only_columns(only or [])
    payload = (
        build_scoped_schema_audit_payload(only_columns=only_columns)
        if only_columns
        else build_schema_audit_payload()
    )
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
    _ensure_backup_target_available(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_target = _temporary_backup_path(target)
    _ensure_backup_target_available(temp_target)
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
    try:
        with temp_target.open("wb") as raw_file:
            sink: BinaryIO
            if temp_target.suffix == ".gz":
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
        size_bytes = _validate_backup_file(temp_target)
        _ensure_backup_target_available(target)
        _publish_backup_file(temp_target, target)
        sha256 = _file_sha256(target)
    except Exception:
        if temp_target.exists():
            temp_target.unlink()
        raise
    print(
        json.dumps(
            {
                "environment": settings.environment,
                "backupFile": str(target),
                "backupSizeBytes": size_bytes,
                "backupSha256": sha256,
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


def _require_production_migration_scope(settings: Settings, only_columns: set[tuple[str, str]] | None) -> None:
    if settings.is_production and not only_columns:
        raise RuntimeError("production migrate-additive --yes 必须至少传入一个 --only table.column，禁止全量执行。")


def _migration_plan_token(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        {
            "onlyColumns": payload.get("onlyColumns", []),
            "additiveStatements": payload.get("additiveStatements", []),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _require_production_plan_token(settings: Settings, *, expected: str, confirmed: str | None) -> None:
    if not settings.is_production:
        return
    if not confirmed:
        raise RuntimeError("production migrate-additive --yes 必须传入 --confirm-plan-token。")
    if confirmed != expected:
        raise RuntimeError("production migrate-additive --yes 的 --confirm-plan-token 与当前计划不匹配。")


def command_migrate_additive(
    settings: Settings,
    *,
    plan: bool,
    yes: bool,
    only: list[str] | None = None,
    backup_max_age_minutes: int = 120,
    confirm_plan_token: str | None = None,
) -> int:
    if plan == yes:
        raise RuntimeError("migrate-additive 必须且只能传入 --plan 或 --yes。")

    only_columns = _parse_only_columns(only or [])
    if yes:
        _require_production_migration_scope(settings, only_columns)
    _ensure_sqlite_parent_dir(settings)
    check_database()
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
    statement_columns = {
        str(item["sql"]): (str(item["table"]), str(item["column"]))
        for item in payload["missingColumns"]
        if item.get("autoMigratable") and item.get("sql") in statements
    }
    payload["planToken"] = _migration_plan_token(payload)

    if plan:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["executable"] else 2

    _require_production_plan_token(settings, expected=str(payload["planToken"]), confirmed=confirm_plan_token)

    if settings.is_production:
        backup_file = require_recent_nonempty_backup(
            settings.private_dir,
            settings.environment,
            max_age_seconds=max(60, int(backup_max_age_minutes) * 60),
        )
        payload["backupFile"] = str(backup_file)
        payload["backupSizeBytes"] = _validate_backup_file(backup_file)
        payload["backupSha256"] = _file_sha256(backup_file)

    if not payload["executable"]:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2

    if statements:
        from app.core.db import get_engine

        engine = get_engine()
        statement_verifications = []
        with engine.begin() as connection:
            for sql in statements:
                connection.execute(text(sql.rstrip(";")))
                target_column = statement_columns.get(sql)
                if target_column is None:
                    continue
                verification = build_scoped_schema_audit_payload(only_columns={target_column})
                verified = bool(verification["ready"])
                statement_verifications.append(
                    {
                        "table": target_column[0],
                        "column": target_column[1],
                        "ready": verified,
                    }
                )
                if not verified:
                    raise RuntimeError(
                        "migrate-additive statement verification failed for "
                        f"{target_column[0]}.{target_column[1]}"
                    )
        payload["statementVerifications"] = statement_verifications
    else:
        payload["statementVerifications"] = []

    after = (
        build_scoped_schema_audit_payload(only_columns=only_columns)
        if only_columns
        else build_schema_audit_payload()
    )
    payload["executedStatements"] = statements
    payload["after"] = after
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if only_columns:
        return 0 if after["ready"] else 2
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
    check_schema_parser = subparsers.add_parser("check-schema")
    check_schema_parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="TABLE.COLUMN",
        help="limit the schema check to a specific column; may be repeated",
    )

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
    migrate_parser.add_argument(
        "--backup-max-age-minutes",
        type=int,
        default=120,
        help="maximum allowed production backup age before --yes execution",
    )
    migrate_parser.add_argument(
        "--confirm-plan-token",
        help="required for production --yes; copy the planToken printed by --plan",
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
        return command_check_schema(settings, only=list(args.only))
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
        return command_migrate_additive(
            settings,
            plan=bool(args.plan),
            yes=bool(args.yes),
            only=list(args.only),
            backup_max_age_minutes=int(args.backup_max_age_minutes),
            confirm_plan_token=args.confirm_plan_token,
        )
    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
