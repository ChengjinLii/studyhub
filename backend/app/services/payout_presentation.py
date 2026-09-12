"""Pure payout report projections; no repositories, providers or transactions."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.models.auth import AuthUser
from app.models.finance import OrderRecord, PayoutScheduleRecord, SettlementRecord
from app.services.read_support import build_payout_qr_url


def recent_dates(entity: PayoutScheduleRecord) -> list[date]:
    result: list[date] = []
    launch = entity.launch_date
    next_date = entity.next_payout_date
    first_cycle = (launch + timedelta(days=7)) if launch is not None else None
    if next_date is not None:
        prev1 = next_date - timedelta(days=30)
        prev2 = next_date - timedelta(days=60)
        if first_cycle is not None and prev2 >= first_cycle:
            result.append(prev2)
        if first_cycle is not None and prev1 >= first_cycle:
            result.append(prev1)
        result.append(next_date)
    elif first_cycle is not None:
        result.extend([first_cycle, first_cycle + timedelta(days=30), first_cycle + timedelta(days=60)])
    if entity.last_payout_date is not None and entity.last_payout_date not in result:
        result.insert(0, entity.last_payout_date)
    return result[:3]


def settlement_detail(entity: SettlementRecord) -> dict[str, Any]:
    return {
        "settlementId": entity.id,
        "sourceType": entity.source_type,
        "sourceId": entity.source_id,
        "materialTitle": entity.material_title,
        "grossAmount": entity.gross_amount,
        "platformFee": entity.platform_fee,
        "payoutAmount": entity.payout_amount,
        "policyVersion": entity.policy_version,
        "scheduledPayoutAt": entity.scheduled_payout_at.isoformat() if entity.scheduled_payout_at else None,
        "createdAt": entity.created_at.isoformat() if entity.created_at else None,
        "status": entity.status,
    }


def account_payload(user: AuthUser) -> dict[str, Any]:
    grade_stages = [item for item in (user.grade_stages or "").split(",") if item]
    return {
        "id": user.id,
        "username": user.username,
        "nickname": user.nickname,
        "signature": user.signature,
        "school": user.school,
        "college": user.college,
        "major": user.major,
        "gradeStages": grade_stages,
        "email": user.email,
        "emailPrivacy": bool(user.email_privacy),
        "avatar": user.avatar,
        "payoutQrUrl": build_payout_qr_url(user.id, user.payout_qr_key),
        "legendaryContributorUntil": user.legendary_contributor_until.isoformat() if user.legendary_contributor_until else None,
        "purchaseCount": 0,
        "saleCount": 0,
    }


def group_paid_orders(rows: list[OrderRecord]) -> dict[int, dict[str, Any]]:
    grouped: dict[int, dict[str, Any]] = {}
    for order in rows:
        if order.uploader_id is None:
            continue
        item = grouped.setdefault(
            int(order.uploader_id),
            {
                "uploaderId": int(order.uploader_id),
                "uploaderUsername": None,
                "uploaderNickname": None,
                "paidDownloadCount": 0,
                "payoutAmount": 0,
                "hasPayoutQr": False,
                "markedPaid": False,
                "markedAt": None,
                "markedById": None,
                "markedByName": None,
                "markedAmountSnapshot": None,
            },
        )
        item["paidDownloadCount"] += 1
        item["payoutAmount"] += int(order.creator_payable_amount or max(0, int(order.amount or 0) - int(order.platform_fee_amount or 0)))
    return grouped
