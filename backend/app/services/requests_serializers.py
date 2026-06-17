from __future__ import annotations

from typing import Any

from app.models.requests import RequestContributionRecord, RequestResponseRecord
from app.services.read_support import serialize_datetime


def amount_to_yuan(cents: int | None) -> float | None:
    if cents is None:
        return None
    return cents / 100.0


def request_response_item(item: RequestResponseRecord) -> dict[str, Any]:
    return {
        "id": item.id,
        "responderName": item.responder_name,
        "message": item.message,
        "materialId": item.material_id,
        "revisionCount": item.revision_count,
        "updatedAt": serialize_datetime(item.updated_at),
        "createdAt": serialize_datetime(item.created_at),
    }


def request_contribution_item(item: RequestContributionRecord) -> dict[str, Any]:
    return {
        "id": item.id,
        "contributorId": item.contributor_id,
        "contributorName": item.contributor_name,
        "type": item.type,
        "amount": amount_to_yuan(item.amount_cents),
        "status": item.status,
        "deadlineTier": item.deadline_tier,
        "deadlineAt": serialize_datetime(item.deadline_at),
        "refundStatus": getattr(item, "refund_status", None),
        "refundedAt": serialize_datetime(getattr(item, "refunded_at", None)),
        "createdAt": serialize_datetime(item.created_at),
    }
