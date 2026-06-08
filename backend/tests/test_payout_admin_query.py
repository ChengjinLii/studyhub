from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.api.deps import get_payout_service
from app.core.db import session_scope
from app.models.finance import CreatorPayoutApplicationRecord, SettlementRecord
from app.services.auth_service import AuthService
from tests.support import seed_read_users


def test_admin_payout_application_list_batches_users_and_earnings(
    client: TestClient,
    auth_service: AuthService,
    monkeypatch,
) -> None:
    _ = client
    seed_read_users(auth_service, with_follow_graph=False)
    now = datetime.now(UTC)

    with session_scope() as session:
        first = CreatorPayoutApplicationRecord(
            user_id=1,
            reviewer_id=3,
            status="PENDING",
            kyc_status="VERIFIED",
            cycle_key="2026-06-08",
        )
        second = CreatorPayoutApplicationRecord(
            user_id=2,
            reviewer_id=3,
            status="APPROVED",
            kyc_status="VERIFIED",
            cycle_key="2026-06-15",
        )
        session.add_all([first, second])
        session.flush()
        session.add_all(
            [
                SettlementRecord(
                    uploader_id=1,
                    gross_amount=1000,
                    platform_fee=100,
                    payout_amount=900,
                    status="PENDING",
                    source_type="ORDER",
                    source_id=9001,
                    scheduled_payout_at=now - timedelta(days=1),
                ),
                SettlementRecord(
                    uploader_id=1,
                    gross_amount=200,
                    platform_fee=20,
                    payout_amount=180,
                    status="PENDING",
                    payout_transfer_id=99,
                    source_type="ORDER",
                    source_id=9002,
                    scheduled_payout_at=now - timedelta(days=1),
                ),
                SettlementRecord(
                    uploader_id=1,
                    gross_amount=300,
                    platform_fee=30,
                    payout_amount=270,
                    status="PENDING",
                    source_type="ORDER",
                    source_id=9003,
                    scheduled_payout_at=now + timedelta(days=1),
                ),
                SettlementRecord(
                    uploader_id=1,
                    gross_amount=400,
                    platform_fee=40,
                    payout_amount=360,
                    status="PAID",
                    source_type="ORDER",
                    source_id=9004,
                    scheduled_payout_at=now - timedelta(days=1),
                ),
                SettlementRecord(
                    uploader_id=2,
                    gross_amount=600,
                    platform_fee=100,
                    payout_amount=500,
                    status="PENDING",
                    source_type="ORDER",
                    source_id=9010,
                    scheduled_payout_at=now - timedelta(days=1),
                ),
            ]
        )
        session.commit()
        first_id = int(first.id)
        second_id = int(second.id)

    service = get_payout_service()
    original_find_users_by_ids = service.auth_repo.find_users_by_ids
    find_users_calls: list[list[int]] = []

    def counted_find_users_by_ids(session, user_ids: list[int]):
        find_users_calls.append(list(user_ids))
        return original_find_users_by_ids(session, user_ids)

    def fail_find_user_by_id(*_args, **_kwargs):
        raise AssertionError("admin payout list should batch applicant and reviewer lookups")

    def fail_list_settlements_for_uploader(*_args, **_kwargs):
        raise AssertionError("admin payout list should batch earnings summaries")

    monkeypatch.setattr(service.auth_repo, "find_users_by_ids", counted_find_users_by_ids)
    monkeypatch.setattr(service.auth_repo, "find_user_by_id", fail_find_user_by_id)
    monkeypatch.setattr(service.finance_repo, "list_settlements_for_uploader", fail_list_settlements_for_uploader)

    with session_scope() as session:
        data = service.list_for_admin(session, page=0, size=20)

    assert find_users_calls == [[2, 1, 3, 3]]
    items = {int(item["id"]): item for item in data["items"]}
    assert items[first_id]["applicantName"] == "Alice Chen"
    assert items[first_id]["reviewerName"] == "超级管理员"
    assert items[first_id]["earnings"] == {
        "grossAmount": 1900,
        "platformFee": 190,
        "payoutAmount": 900,
        "orderCount": 4,
        "unclaimedPayoutTotal": 1350,
    }
    assert items[second_id]["applicantName"] == "白山"
    assert items[second_id]["reviewerName"] == "超级管理员"
    assert items[second_id]["earnings"]["payoutAmount"] == 500
