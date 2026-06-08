from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.repos import finance_repo as finance_repo_module
from app.repos.finance_repo import FinanceRepository


def _legacy_session() -> Session:
    finance_repo_module._TABLE_COLUMN_CACHE.clear()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE materials (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    uploader_id INTEGER NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    material_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    created_at DATETIME NULL,
                    updated_at DATETIME NULL,
                    out_trade_no TEXT NULL,
                    trade_no TEXT NULL,
                    paid_at DATETIME NULL,
                    pay_channel TEXT NULL,
                    commission_rate REAL NULL,
                    platform_fee_amount INTEGER NULL,
                    creator_payable_amount INTEGER NULL,
                    policy_version TEXT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE settlements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NULL,
                    material_id INTEGER NULL,
                    uploader_id INTEGER NULL,
                    gross_amount INTEGER NOT NULL DEFAULT 0,
                    platform_fee INTEGER NOT NULL DEFAULT 0,
                    payout_amount INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    scheduled_payout_at DATETIME NULL,
                    processed_at DATETIME NULL,
                    created_at DATETIME NULL,
                    updated_at DATETIME NULL,
                    notes TEXT NULL,
                    policy_version TEXT NULL,
                    source_type TEXT NOT NULL,
                    source_id INTEGER NOT NULL,
                    policy_id TEXT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE admin_monthly_payout_marks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    month_key TEXT NOT NULL,
                    uploader_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    amount_snapshot INTEGER NULL,
                    marked_by INTEGER NULL,
                    marked_at DATETIME NULL,
                    created_at DATETIME NULL,
                    updated_at DATETIME NULL
                )
                """
            )
        )
    return Session(engine)


def test_settlement_reads_tolerate_missing_material_title_and_transfer_id() -> None:
    repo = FinanceRepository()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with _legacy_session() as session:
        session.execute(text("INSERT INTO materials (id, title, uploader_id) VALUES (10, '信号与系统', 2)"))
        session.execute(
            text(
                """
                INSERT INTO settlements (
                    order_id, material_id, uploader_id, gross_amount, platform_fee,
                    payout_amount, status, scheduled_payout_at, created_at, updated_at,
                    source_type, source_id, policy_version, policy_id
                )
                VALUES (
                    100, 10, 2, 500, 50, 450, 'PENDING', :due_at, :created_at, :created_at,
                    'ORDER', 100, 'v1', 'MARKET'
                )
                """
            ),
            {"due_at": now - timedelta(days=1), "created_at": now},
        )
        session.commit()

        items = repo.list_settlements_for_uploader(session, 2)
        source = repo.find_settlement_by_source(session, "ORDER", 100)
        claimable = repo.list_claimable_due_settlements_for_uploader(session, 2, now)
        summary = repo.summarize_settlements_for_uploaders(session, [2], now)

    assert items[0].material_title == "信号与系统"
    assert items[0].payout_transfer_id is None
    assert source is not None and source.order_id == 100
    assert [item.id for item in claimable] == [items[0].id]
    assert summary[2] == {
        "grossAmount": 500,
        "platformFee": 50,
        "payoutAmount": 450,
        "orderCount": 1,
        "unclaimedPayoutTotal": 450,
    }


def test_legacy_settlement_save_updates_only_existing_columns() -> None:
    repo = FinanceRepository()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with _legacy_session() as session:
        session.execute(text("INSERT INTO materials (id, title, uploader_id) VALUES (10, '信号与系统', 2)"))
        session.execute(
            text(
                """
                INSERT INTO settlements (
                    order_id, material_id, uploader_id, gross_amount, platform_fee,
                    payout_amount, status, scheduled_payout_at, created_at, updated_at,
                    source_type, source_id, policy_version, policy_id
                )
                VALUES (
                    100, 10, 2, 500, 50, 450, 'PENDING', :due_at, :created_at, :created_at,
                    'ORDER', 100, 'v1', 'MARKET'
                )
                """
            ),
            {"due_at": now - timedelta(days=1), "created_at": now},
        )
        session.commit()

        settlement = repo.list_settlements_for_uploader(session, 2)[0]
        settlement.status = "PAID"
        settlement.processed_at = now
        settlement.payout_transfer_id = 99
        repo.save_settlement(session, settlement)
        session.commit()

        row = session.execute(text("SELECT status, processed_at FROM settlements WHERE id = :id"), {"id": settlement.id}).mappings().one()

    assert row["status"] == "PAID"
    assert row["processed_at"] is not None


def test_legacy_order_reads_backfill_creator_and_title_from_materials() -> None:
    repo = FinanceRepository()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with _legacy_session() as session:
        session.execute(text("INSERT INTO materials (id, title, uploader_id) VALUES (10, '信号与系统', 2)"))
        session.execute(
            text(
                """
                INSERT INTO orders (
                    user_id, material_id, amount, status, channel, created_at, updated_at,
                    out_trade_no, trade_no, paid_at, pay_channel, commission_rate,
                    platform_fee_amount, creator_payable_amount, policy_version
                )
                VALUES (
                    7, 10, 500, 'PAID', 'alipay', :created_at, :created_at,
                    'ORDER100', 'TRADE100', :paid_at, 'alipay', 0.1,
                    50, 450, 'v1'
                )
                """
            ),
            {"created_at": now, "paid_at": now},
        )
        session.commit()

        by_creator = repo.list_paid_orders_for_creator_between(session, 2, now - timedelta(hours=1), now + timedelta(hours=1))
        monthly = repo.list_paid_orders_between(session, now - timedelta(hours=1), now + timedelta(hours=1))
        latest = repo.find_order_by_out_trade_no(session, "ORDER100")

    assert [order.uploader_id for order in by_creator] == [2]
    assert monthly[0].material_title == "信号与系统"
    assert latest is not None and latest.creator_payable_amount == 450


def test_legacy_monthly_payout_marks_use_marked_by_column() -> None:
    repo = FinanceRepository()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with _legacy_session() as session:
        session.execute(
            text(
                """
                INSERT INTO admin_monthly_payout_marks (
                    month_key, uploader_id, status, amount_snapshot, marked_by, marked_at, created_at, updated_at
                )
                VALUES ('2026-01', 2, 'PAID', 450, 9, :marked_at, :marked_at, :marked_at)
                """
            ),
            {"marked_at": now},
        )
        session.commit()

        mark = repo.find_monthly_payout_mark(session, "2026-01", 2)
        marks = repo.list_monthly_payout_marks(session, "2026-01")

    assert mark is not None and mark.marked_by_id == 9
    assert [(item.uploader_id, item.amount_snapshot) for item in marks] == [(2, 450)]
