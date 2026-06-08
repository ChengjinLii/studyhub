from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import json
import os
import pytest

from app.core.config import Settings, get_settings
from app.core.db import reset_database_runtime
from app.ops.db_admin import (
    _validate_backup_file,
    _migration_plan_token,
    _require_production_plan_token,
    _require_production_migration_scope,
    command_backup,
    command_check,
    command_check_schema,
    command_init_schema,
    command_migrate_additive,
    command_restore,
)
from app.ops.schema_audit import (
    build_scoped_schema_audit_payload,
    compare_metadata_schema,
    require_recent_nonempty_backup,
    select_additive_migration_scope,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PRIVATE_FIXTURE_DIR = REPO_ROOT / "private"


def _reset_runtime_state() -> None:
    reset_database_runtime()
    get_settings.cache_clear()


def _write_private_env(root: Path, environment: str, content: str) -> Path:
    private_dir = root / "private"
    private_dir.mkdir(parents=True, exist_ok=True)
    (private_dir / f".env.{environment}").write_text(content.strip() + "\n", encoding="utf-8")
    return private_dir


def test_db_admin_local_dev_check_then_init_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "local-dev")
    monkeypatch.setenv("STUDYHUB_LOCAL_DEV_ROOT_DIR", str(tmp_path / ".local-dev"))
    monkeypatch.setenv("STUDYHUB_JWT_SECRET", "studyhub-fastapi-test-secret-1234567890abcdefghijkl")

    _reset_runtime_state()
    settings = get_settings()

    assert command_check(settings) == 2
    assert command_init_schema(settings, allow_preview=False) == 0
    assert command_check(settings) == 0
    assert command_check_schema(settings) == 0

    _reset_runtime_state()


def test_schema_audit_reports_known_production_drift_columns() -> None:
    from sqlalchemy.dialects import mysql

    from app.models import Base

    actual_tables = set(Base.metadata.tables)
    actual_columns_by_table = {
        table_name: {column.name for column in table.columns}
        for table_name, table in Base.metadata.tables.items()
    }
    actual_columns_by_table["market_items"].remove("source")
    actual_columns_by_table["orders"].remove("uploader_id")

    payload = compare_metadata_schema(
        metadata=Base.metadata,
        actual_tables=actual_tables,
        actual_columns_by_table=actual_columns_by_table,
        actual_indexes_by_table={},
        dialect=mysql.dialect(),
    )

    missing = {(item["table"], item["column"]): item for item in payload["missingColumns"]}
    assert ("market_items", "source") in missing
    assert ("orders", "uploader_id") in missing
    assert missing[("market_items", "source")]["autoMigratable"] is True
    assert "ADD COLUMN" in missing[("market_items", "source")]["sql"]
    assert "DEFAULT 'local'" in missing[("market_items", "source")]["sql"]
    assert missing[("orders", "uploader_id")]["autoMigratable"] is True
    assert "ADD COLUMN" in missing[("orders", "uploader_id")]["sql"]
    assert payload["destructiveChanges"] == []
    assert payload["ready"] is False
    assert payload["executable"] is True

    scoped = select_additive_migration_scope(
        payload,
        metadata=Base.metadata,
        only_columns={("market_items", "source")},
    )

    assert scoped["scope"] == "selected"
    assert scoped["onlyColumns"] == ["market_items.source"]
    assert scoped["allMissingColumnCount"] == 2
    assert [(item["table"], item["column"]) for item in scoped["missingColumns"]] == [("market_items", "source")]
    assert scoped["additiveStatements"] == [missing[("market_items", "source")]["sql"]]
    assert scoped["executable"] is True


def test_schema_audit_reports_type_and_nullable_warnings_separately() -> None:
    from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table
    from sqlalchemy.dialects import mysql

    expected = MetaData()
    Table(
        "market_items",
        expected,
        Column("id", Integer, primary_key=True),
        Column("source", String(16), nullable=False, default="local"),
        Column("enabled", Boolean, nullable=True),
    )

    payload = compare_metadata_schema(
        metadata=expected,
        actual_tables={"market_items"},
        actual_columns_by_table={"market_items": {"id", "source", "enabled"}},
        actual_column_details_by_table={
            "market_items": {
                "source": {"name": "source", "type": String(32), "nullable": True, "default": "'legacy'"},
                "enabled": {"name": "enabled", "type": mysql.TINYINT(display_width=1), "nullable": True},
            }
        },
        actual_indexes_by_table={},
        dialect=mysql.dialect(),
    )

    warning_keys = {(item["table"], item["column"], item["kind"]) for item in payload["columnWarnings"]}
    assert warning_keys == {
        ("market_items", "source", "type"),
        ("market_items", "source", "nullable"),
        ("market_items", "source", "default"),
    }
    assert payload["missingColumns"] == []
    assert payload["destructiveChanges"] == []
    assert payload["ready"] is True


def test_scoped_schema_audit_ready_reflects_selected_columns() -> None:
    from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine

    expected = MetaData()
    Table(
        "market_items",
        expected,
        Column("id", Integer, primary_key=True),
        Column("source", String(16), nullable=False, default="local"),
    )
    actual = MetaData()
    Table("market_items", actual, Column("id", Integer, primary_key=True))
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    actual.create_all(bind=engine)

    missing = build_scoped_schema_audit_payload(
        engine=engine,
        metadata=expected,
        only_columns={("market_items", "source")},
    )
    assert missing["ready"] is False
    assert [(item["table"], item["column"]) for item in missing["missingColumns"]] == [("market_items", "source")]

    present = build_scoped_schema_audit_payload(
        engine=engine,
        metadata=expected,
        only_columns={("market_items", "id")},
    )
    assert present["ready"] is True
    assert present["missingColumns"] == []


def test_scoped_schema_audit_blocks_requested_column_when_table_is_missing() -> None:
    from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine

    expected = MetaData()
    Table(
        "market_items",
        expected,
        Column("id", Integer, primary_key=True),
        Column("source", String(16), nullable=False, default="local"),
    )
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

    payload = build_scoped_schema_audit_payload(
        engine=engine,
        metadata=expected,
        only_columns={("market_items", "source")},
    )

    assert payload["ready"] is False
    assert payload["executable"] is False
    assert payload["missingTables"] == ["market_items"]
    assert payload["alreadyPresentColumns"] == []
    assert payload["additiveStatements"] == []


def test_scoped_schema_audit_reports_selected_missing_indexes_separately() -> None:
    from sqlalchemy import Column, Integer, MetaData, Table
    from sqlalchemy.dialects import mysql

    expected = MetaData()
    Table(
        "orders",
        expected,
        Column("id", Integer, primary_key=True),
        Column("uploader_id", Integer, nullable=True, index=True),
    )

    payload = compare_metadata_schema(
        metadata=expected,
        actual_tables={"orders"},
        actual_columns_by_table={"orders": {"id", "uploader_id"}},
        actual_indexes_by_table={"orders": set()},
        dialect=mysql.dialect(),
    )
    scoped = select_additive_migration_scope(
        payload,
        metadata=expected,
        only_columns={("orders", "uploader_id")},
    )

    assert scoped["ready"] is True
    assert scoped["missingColumns"] == []
    assert scoped["allMissingIndexCount"] == 1
    assert scoped["missingIndexes"] == [
        {
            "table": "orders",
            "index": "ix_orders_uploader_id",
            "columns": ["uploader_id"],
            "sql": "CREATE INDEX `ix_orders_uploader_id` ON `orders` (`uploader_id`);",
        }
    ]


def test_schema_audit_reports_only_relevant_legacy_compatibility_tables() -> None:
    from sqlalchemy.dialects import mysql

    from app.models import Base

    actual_tables = set(Base.metadata.tables)
    actual_tables.remove("auth_users")
    actual_tables.add("users")
    actual_tables.add("unrelated_runtime_table")

    payload = compare_metadata_schema(
        metadata=Base.metadata,
        actual_tables=actual_tables,
        actual_columns_by_table={
            table_name: {column.name for column in table.columns}
            for table_name, table in Base.metadata.tables.items()
            if table_name in actual_tables
        },
        actual_indexes_by_table={},
        dialect=mysql.dialect(),
    )

    auth_compat = next(item for item in payload["legacyCompatibleTables"] if item["table"] == "auth_users")
    assert auth_compat["coveredBy"] == ["users"]


def test_require_recent_backup_rejects_stale_backup(tmp_path: Path) -> None:
    backup_root = tmp_path / "backups" / "production"
    backup_root.mkdir(parents=True)
    backup_file = backup_root / "studyhub-production-old.sql.gz"
    backup_file.write_bytes(b"backup")
    now = datetime(2026, 6, 8, 12, 0, tzinfo=UTC)
    stale_ts = (now - timedelta(minutes=121)).timestamp()
    os.utime(backup_file, (stale_ts, stale_ts))

    with pytest.raises(RuntimeError, match="最近 120 分钟"):
        require_recent_nonempty_backup(tmp_path, "production", max_age_seconds=120 * 60, now=now)


def test_require_recent_backup_accepts_latest_nonempty_backup(tmp_path: Path) -> None:
    backup_root = tmp_path / "backups" / "production"
    backup_root.mkdir(parents=True)
    empty_backup = backup_root / "studyhub-production-empty.sql.gz"
    empty_backup.write_bytes(b"")
    backup_file = backup_root / "studyhub-production-fresh.sql.gz"
    backup_file.write_bytes(b"backup")
    now = datetime(2026, 6, 8, 12, 0, tzinfo=UTC)
    fresh_ts = (now - timedelta(minutes=30)).timestamp()
    os.utime(backup_file, (fresh_ts, fresh_ts))

    assert require_recent_nonempty_backup(tmp_path, "production", max_age_seconds=120 * 60, now=now) == backup_file


def test_validate_backup_file_accepts_readable_gzip(tmp_path: Path) -> None:
    import gzip

    backup_file = tmp_path / "backup.sql.gz"
    with gzip.open(backup_file, "wb") as target:
        target.write(b"CREATE TABLE example (id int);\n")

    assert _validate_backup_file(backup_file) == backup_file.stat().st_size


def test_validate_backup_file_rejects_corrupt_gzip(tmp_path: Path) -> None:
    backup_file = tmp_path / "backup.sql.gz"
    backup_file.write_bytes(b"not gzip")

    with pytest.raises(RuntimeError, match="gzip 校验失败"):
        _validate_backup_file(backup_file)


def test_validate_backup_file_rejects_empty_file(tmp_path: Path) -> None:
    backup_file = tmp_path / "backup.sql"
    backup_file.write_bytes(b"")

    with pytest.raises(RuntimeError, match="备份文件为空"):
        _validate_backup_file(backup_file)


def test_production_migrate_requires_explicit_only_scope() -> None:
    settings = Settings(environment="production")

    with pytest.raises(RuntimeError, match="必须至少传入一个 --only"):
        _require_production_migration_scope(settings, None)

    _require_production_migration_scope(settings, {("market_items", "source")})


def test_migration_plan_token_is_stable_and_sensitive() -> None:
    base = {
        "onlyColumns": ["market_items.source"],
        "additiveStatements": ["ALTER TABLE `market_items` ADD COLUMN `source` VARCHAR(16) NOT NULL DEFAULT 'local';"],
    }
    same = {
        "additiveStatements": ["ALTER TABLE `market_items` ADD COLUMN `source` VARCHAR(16) NOT NULL DEFAULT 'local';"],
        "onlyColumns": ["market_items.source"],
    }
    changed = {
        "onlyColumns": ["orders.uploader_id"],
        "additiveStatements": ["ALTER TABLE `orders` ADD COLUMN `uploader_id` INTEGER NULL;"],
    }

    assert _migration_plan_token(base) == _migration_plan_token(same)
    assert _migration_plan_token(base) != _migration_plan_token(changed)


def test_production_migrate_requires_matching_plan_token() -> None:
    settings = Settings(environment="production")

    with pytest.raises(RuntimeError, match="confirm-plan-token"):
        _require_production_plan_token(settings, expected="abc123", confirmed=None)
    with pytest.raises(RuntimeError, match="不匹配"):
        _require_production_plan_token(settings, expected="abc123", confirmed="wrong")

    _require_production_plan_token(settings, expected="abc123", confirmed="abc123")


def test_migrate_additive_yes_uses_scoped_after_check_for_only_columns(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.ops import db_admin as db_admin_module

    settings = Settings(environment="local-dev")
    expected_only_columns = {("market_items", "source")}
    seen_only_columns: dict[str, set[tuple[str, str]] | None] = {}

    def fake_plan_payload(*, only_columns: set[tuple[str, str]] | None) -> dict[str, object]:
        seen_only_columns["plan"] = only_columns
        return {
            "scope": "selected",
            "onlyColumns": ["market_items.source"],
            "missingTables": [],
            "missingColumns": [],
            "manualReviewColumns": [],
            "unknownRequestedColumns": [],
            "alreadyPresentColumns": [{"table": "market_items", "column": "source"}],
            "additiveStatements": [],
            "executable": True,
            "ready": True,
            "statementCount": 0,
            "readyAfterMigration": True,
        }

    def fake_after_payload(*, only_columns: set[tuple[str, str]] | None) -> dict[str, object]:
        seen_only_columns["after"] = only_columns
        return {
            "scope": "selected",
            "onlyColumns": ["market_items.source"],
            "missingTables": ["market_items"],
            "missingColumns": [],
            "manualReviewColumns": [],
            "unknownRequestedColumns": [],
            "alreadyPresentColumns": [],
            "additiveStatements": [],
            "executable": False,
            "ready": False,
        }

    monkeypatch.setattr(db_admin_module, "_ensure_sqlite_parent_dir", lambda settings: None)
    monkeypatch.setattr(db_admin_module, "check_database", lambda: None)
    monkeypatch.setattr(
        db_admin_module,
        "build_scoped_additive_migration_payload",
        fake_plan_payload,
    )
    monkeypatch.setattr(
        db_admin_module,
        "build_scoped_schema_audit_payload",
        fake_after_payload,
    )
    monkeypatch.setattr(
        db_admin_module,
        "build_schema_audit_payload",
        lambda: (_ for _ in ()).throw(AssertionError("expected scoped after-check")),
    )

    assert command_migrate_additive(settings, plan=False, yes=True, only=["market_items.source"]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["after"]["missingTables"] == ["market_items"]
    assert payload["after"]["ready"] is False
    assert payload["planToken"] == _migration_plan_token(payload)
    assert seen_only_columns == {"plan": expected_only_columns, "after": expected_only_columns}


def test_migrate_additive_yes_verifies_each_executed_statement(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.ops import db_admin as db_admin_module

    settings = Settings(environment="local-dev")
    sql = "ALTER TABLE `market_items` ADD COLUMN `source` VARCHAR(16) NOT NULL DEFAULT 'local';"
    executed_sql: list[str] = []
    audit_calls: list[set[tuple[str, str]]] = []

    class FakeConnection:
        def execute(self, statement: object) -> None:
            executed_sql.append(str(statement))

    class FakeBegin:
        def __enter__(self) -> FakeConnection:
            return FakeConnection()

        def __exit__(self, *args: object) -> None:
            return None

    class FakeEngine:
        def begin(self) -> FakeBegin:
            return FakeBegin()

    def fake_plan_payload(*, only_columns: set[tuple[str, str]] | None) -> dict[str, object]:
        return {
            "scope": "selected",
            "onlyColumns": ["market_items.source"],
            "missingTables": [],
            "missingColumns": [
                {
                    "table": "market_items",
                    "column": "source",
                    "autoMigratable": True,
                    "sql": sql,
                }
            ],
            "manualReviewColumns": [],
            "unknownRequestedColumns": [],
            "alreadyPresentColumns": [],
            "additiveStatements": [sql],
            "executable": True,
            "ready": False,
            "statementCount": 1,
            "readyAfterMigration": True,
        }

    def fake_after_payload(*, only_columns: set[tuple[str, str]] | None) -> dict[str, object]:
        audit_calls.append(set(only_columns or set()))
        return {
            "scope": "selected",
            "onlyColumns": ["market_items.source"],
            "missingTables": [],
            "missingColumns": [],
            "manualReviewColumns": [],
            "unknownRequestedColumns": [],
            "alreadyPresentColumns": [{"table": "market_items", "column": "source"}],
            "additiveStatements": [],
            "executable": True,
            "ready": True,
        }

    monkeypatch.setattr(db_admin_module, "_ensure_sqlite_parent_dir", lambda settings: None)
    monkeypatch.setattr(db_admin_module, "check_database", lambda: None)
    monkeypatch.setattr("app.core.db.get_engine", lambda: FakeEngine())
    monkeypatch.setattr(db_admin_module, "build_scoped_additive_migration_payload", fake_plan_payload)
    monkeypatch.setattr(db_admin_module, "build_scoped_schema_audit_payload", fake_after_payload)

    assert command_migrate_additive(settings, plan=False, yes=True, only=["market_items.source"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert len(executed_sql) == 1
    assert "ADD COLUMN `source`" in executed_sql[0]
    assert audit_calls == [{("market_items", "source")}, {("market_items", "source")}]
    assert payload["statementVerifications"] == [
        {"table": "market_items", "column": "source", "ready": True}
    ]


def test_db_admin_backup_rejects_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "local-dev")
    monkeypatch.setenv("STUDYHUB_LOCAL_DEV_ROOT_DIR", str(tmp_path / ".local-dev"))
    monkeypatch.setenv("STUDYHUB_JWT_SECRET", "studyhub-fastapi-test-secret-1234567890abcdefghijkl")

    _reset_runtime_state()
    settings = get_settings()

    with pytest.raises(RuntimeError, match="不是 MySQL"):
        command_backup(settings, output=None)

    _reset_runtime_state()


def test_db_admin_restore_requires_explicit_preview_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    private_dir = _write_private_env(
        tmp_path,
        "preview",
        """
        STUDYHUB_ENVIRONMENT=preview
        STUDYHUB_DATABASE_URL=mysql+pymysql://preview_user:preview_pass@127.0.0.1:3306/studyhub_preview
        STUDYHUB_JWT_SECRET=preview-secret-abcdefghijklmnopqrstuvwxyz
        STUDYHUB_MAIL_PROVIDER=smtp
        STUDYHUB_SMTP_HOST=smtp.preview.example.com
        STUDYHUB_SMTP_FROM_EMAIL=preview@example.com
        STUDYHUB_STORAGE_PROVIDER=local_fs
        STUDYHUB_PAYMENT_PROVIDER=local_alipay
        """,
    )
    backup_file = tmp_path / "preview.sql.gz"
    backup_file.write_bytes(b"dummy")
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "preview")
    monkeypatch.setenv("STUDYHUB_PRIVATE_DIR_PATH", str(private_dir))

    _reset_runtime_state()
    settings = get_settings()

    with pytest.raises(RuntimeError, match="yes-preview-restore"):
        command_restore(settings, input_path=backup_file, yes_preview_restore=False)

    _reset_runtime_state()


def test_db_admin_init_schema_rejects_production(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mock_private_key = PRIVATE_FIXTURE_DIR / "mock-alipay-private.pem"
    mock_public_key = PRIVATE_FIXTURE_DIR / "mock-alipay-public.pem"
    private_dir = _write_private_env(
        tmp_path,
        "production",
        f"""
        STUDYHUB_ENVIRONMENT=production
        STUDYHUB_DATABASE_URL=mysql+pymysql://prod_user:prod_pass@127.0.0.1:3306/studyhub_prod
        STUDYHUB_JWT_SECRET=prod-secret-abcdefghijklmnopqrstuvwxyz
        STUDYHUB_MAIL_PROVIDER=smtp
        STUDYHUB_SMTP_HOST=smtp.prod.example.com
        STUDYHUB_SMTP_FROM_EMAIL=noreply@example.com
        STUDYHUB_STORAGE_PROVIDER=oss
        STUDYHUB_OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
        STUDYHUB_OSS_BUCKET=studyhub-prod
        STUDYHUB_OSS_ACCESS_KEY_ID=prod-ak
        STUDYHUB_OSS_ACCESS_KEY_SECRET=prod-sk
        STUDYHUB_LOCK_PROVIDER=redis
        STUDYHUB_REDIS_URL=redis://127.0.0.1:6379/0
        STUDYHUB_PAYMENT_PROVIDER=alipay_page
        STUDYHUB_ALIPAY_APP_ID=2021000000000000
        STUDYHUB_ALIPAY_APP_PRIVATE_KEY_PATH={mock_private_key}
        STUDYHUB_ALIPAY_PUBLIC_KEY_PATH={mock_public_key}
        STUDYHUB_PAYOUT_TRANSFER_PROVIDER=alipay_transfer
        STUDYHUB_KYC_PROVIDER=aliyun_cloud_auth
        STUDYHUB_ALIBABA_CLOUD_ACCESS_KEY_ID=aliyun-ak
        STUDYHUB_ALIBABA_CLOUD_ACCESS_KEY_SECRET=aliyun-sk
        """,
    )
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "production")
    monkeypatch.setenv("STUDYHUB_PRIVATE_DIR_PATH", str(private_dir))

    _reset_runtime_state()
    settings = get_settings()

    with pytest.raises(RuntimeError, match="production 模式禁止"):
        command_init_schema(settings, allow_preview=False)

    _reset_runtime_state()
