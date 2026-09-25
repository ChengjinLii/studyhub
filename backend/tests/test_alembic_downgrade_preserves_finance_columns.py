from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.core.config import get_settings


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_downgrading_finance_migrations_keeps_settlement_binding_and_refund_columns(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "alembic-downgrade.sqlite3"
    monkeypatch.setenv("STUDYHUB_DATABASE_URL", f"sqlite+pysqlite:///{database_path}")
    get_settings.cache_clear()
    try:
        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        command.upgrade(config, "0004_contribution_refund_fields")
        command.downgrade(config, "0002_add_market_source_and_order_uploader")

        engine = create_engine(f"sqlite+pysqlite:///{database_path}", future=True)
        try:
            with engine.connect() as connection:
                inspector = inspect(connection)
                settlement_columns = {column["name"] for column in inspector.get_columns("settlements")}
                contribution_columns = {column["name"] for column in inspector.get_columns("material_request_contributions")}
        finally:
            engine.dispose()
        assert "payout_transfer_id" in settlement_columns
        assert {"refund_status", "refund_trade_no", "refunded_at"} <= contribution_columns
    finally:
        get_settings.cache_clear()
