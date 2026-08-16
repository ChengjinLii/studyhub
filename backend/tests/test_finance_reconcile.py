from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.finance import FinanceInstructionRecord, PayoutTransferRecord, SettlementRecord
from app.models.requests import RequestContributionRecord
from app.ops.finance_reconcile import build_finance_reconciliation


def test_finance_reconciliation_detects_stale_and_mismatched_records() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    for table in (
        FinanceInstructionRecord.__table__,
        PayoutTransferRecord.__table__,
        SettlementRecord.__table__,
        RequestContributionRecord.__table__,
    ):
        table.create(bind=engine)
    now = datetime.now(UTC)
    old = now - timedelta(hours=2)
    with Session(engine) as session:
        instruction = FinanceInstructionRecord(
            operation_key="payout-transfer:7",
            instruction_type="PAYOUT_TRANSFER",
            aggregate_type="PAYOUT_TRANSFER",
            aggregate_id=7,
            status="FAILED",
        )
        instruction.created_at = old
        instruction.updated_at = old
        transfer = PayoutTransferRecord(
            id=7,
            payout_application_id=9,
            out_biz_no="PAYOUT-7",
            status="SUCCESS",
            amount=100,
        )
        settlement = SettlementRecord(
            id=8,
            payout_transfer_id=7,
            status="PENDING",
            source_type="ORDER",
            source_id=1,
        )
        contribution = RequestContributionRecord(
            id=10,
            request_id=2,
            type="OWNER",
            amount_cents=100,
            status="REFUNDING",
            refund_status="PENDING",
        )
        contribution.created_at = old
        contribution.updated_at = old
        session.add_all([instruction, transfer, settlement, contribution])
        session.commit()

    report = build_finance_reconciliation(engine, now=now)

    assert report["ok"] is False
    assert report["payouts"]["inconsistentSettlements"] == 1
    assert report["refunds"]["stale"] == 1
    assert {item["code"] for item in report["issues"]} >= {
        "FAILED_FINANCE_INSTRUCTIONS",
        "PAYOUT_SETTLEMENT_MISMATCH",
        "STALE_REQUEST_REFUNDS",
    }
