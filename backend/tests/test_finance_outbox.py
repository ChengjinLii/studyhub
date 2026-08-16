from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.finance import FinanceInstructionRecord
from app.repos.finance_repo import FinanceRepository


def test_finance_outbox_defaults_on_only_in_production() -> None:
    assert Settings(environment="production").resolved_finance_outbox_enabled is True
    assert Settings(environment="local-dev").resolved_finance_outbox_enabled is False
    assert Settings(environment="production", finance_outbox_enabled=False).resolved_finance_outbox_enabled is False


def test_finance_instruction_repository_recovers_stale_processing_rows() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    FinanceInstructionRecord.__table__.create(bind=engine)
    repo = FinanceRepository()
    now = datetime.now(UTC)
    with Session(engine) as session:
        repo.save_finance_instruction(
            session,
            FinanceInstructionRecord(
                operation_key="payout-transfer:1",
                instruction_type="PAYOUT_TRANSFER",
                aggregate_type="PAYOUT_TRANSFER",
                aggregate_id=1,
                status="PROCESSING",
                claimed_at=now - timedelta(minutes=10),
            ),
        )
        session.commit()
        ready = repo.list_ready_finance_instructions(
            session,
            "PAYOUT_TRANSFER",
            now,
            stale_before=now - timedelta(minutes=5),
        )
    assert [item.operation_key for item in ready] == ["payout-transfer:1"]
