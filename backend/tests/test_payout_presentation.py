from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from app.services.payout_service import PayoutService


@pytest.mark.parametrize("launch,next_date,last_date,expected", [
    (None, None, None, []),
    (date(2026, 1, 1), None, None, [date(2026, 1, 8), date(2026, 2, 7), date(2026, 3, 9)]),
    (date(2026, 1, 1), date(2026, 3, 9), None, [date(2026, 1, 8), date(2026, 2, 7), date(2026, 3, 9)]),
    (None, date(2026, 3, 9), date(2026, 2, 7), [date(2026, 2, 7), date(2026, 3, 9)]),
    (date(2026, 1, 1), None, date(2026, 1, 2), [date(2026, 1, 2), date(2026, 1, 8), date(2026, 2, 7)]),
    (date(2026, 1, 1), date(2026, 1, 8), date(2026, 1, 8), [date(2026, 1, 8)]),
])
def test_payout_schedule_preserves_existing_calendar_rules(launch, next_date, last_date, expected):
    service = object.__new__(PayoutService)
    schedule = SimpleNamespace(launch_date=launch, next_payout_date=next_date, last_payout_date=last_date)
    assert service._compute_recent_dates(schedule) == expected
    assert service._to_schedule_payload(schedule) == {
        "launchDate": launch.isoformat() if launch else None,
        "lastPayoutDate": last_date.isoformat() if last_date else None,
        "nextPayoutDate": next_date.isoformat() if next_date else None,
        "recentPayoutDates": [item.isoformat() for item in expected],
    }


@pytest.mark.parametrize("timestamp", [None, datetime(2026, 1, 1, tzinfo=UTC)])
def test_settlement_projection_keeps_cents_nulls_and_dates(timestamp):
    service = object.__new__(PayoutService)
    record = SimpleNamespace(id=1, source_type="ORDER", source_id=2, material_title=None,
                             gross_amount=101, platform_fee=10, payout_amount=91, policy_version="v1",
                             scheduled_payout_at=timestamp, created_at=timestamp, status="PENDING")
    assert service._to_settlement_detail(record) == {
        "settlementId": 1, "sourceType": "ORDER", "sourceId": 2, "materialTitle": None,
        "grossAmount": 101, "platformFee": 10, "payoutAmount": 91, "policyVersion": "v1",
        "scheduledPayoutAt": timestamp.isoformat() if timestamp else None,
        "createdAt": timestamp.isoformat() if timestamp else None, "status": "PENDING",
    }


def test_monthly_overview_preserves_zero_fallback_marks_and_order():
    service = object.__new__(PayoutService)
    calls = []

    def orders(_session, start, end):
        calls.append((start, end))
        return [
            SimpleNamespace(uploader_id=None),
            SimpleNamespace(uploader_id=2, creator_payable_amount=0, amount=100, platform_fee_amount=10),
            SimpleNamespace(uploader_id=1, creator_payable_amount=90, amount=200, platform_fee_amount=0),
            SimpleNamespace(uploader_id=3, creator_payable_amount=None, amount=50, platform_fee_amount=100),
        ]

    service.finance_repo = SimpleNamespace(
        list_paid_orders_between=orders,
        list_monthly_payout_marks=lambda *_: [SimpleNamespace(uploader_id=4, amount_snapshot=25)],
    )
    service._hydrate_monthly_overview_items = lambda *_: None
    result = service.get_monthly_overview(None, month_key_raw="2026-12")
    assert calls == [(datetime(2026, 11, 30, 16, tzinfo=UTC), datetime(2026, 12, 31, 16, tzinfo=UTC))]
    assert result["periodStart"] == "2026-12-01"
    assert result["periodEnd"] == "2026-12-31"
    assert result["totalPayoutAmount"] == 205
    assert result["totalPaidDownloadCount"] == 3
    assert result["creatorCount"] == 4
    assert [item["uploaderId"] for item in result["items"]] == [1, 2, 4, 3]
    assert [item["payoutAmount"] for item in result["items"]] == [90, 90, 25, 0]
    assert all(not item["markedPaid"] for item in result["items"])
