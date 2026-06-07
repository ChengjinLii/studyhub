from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import get_settings
from app.core.db import reset_database_runtime
from app.ops.db_admin import command_backup, command_check, command_check_schema, command_init_schema, command_restore
from app.ops.schema_audit import compare_metadata_schema, select_additive_migration_scope

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
