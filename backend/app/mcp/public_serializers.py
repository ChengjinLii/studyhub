from __future__ import annotations

from typing import Any

from app.mcp.schemas import (
    validate_discovery_material,
    validate_public_market,
    validate_public_material,
    validate_public_request,
)
from app.mcp.serializers import material_referral_url


MAX_TEXT_LENGTH = 1200
DISCOVERY_SUMMARY_MAX_LENGTH = 260


def clamp_text(value: Any, *, max_length: int = MAX_TEXT_LENGTH) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 1].rstrip()}..."


def public_material(item: dict[str, Any]) -> dict[str, Any]:
    tags = item.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    return validate_public_material({
        "id": item.get("id"),
        "title": item.get("title"),
        "description": clamp_text(item.get("description")),
        "school": item.get("school"),
        "college": item.get("college"),
        "major": item.get("major"),
        "tags": tags,
        "free": bool(item.get("free")),
        "downloadCount": item.get("downloadCount") or 0,
        "ratingAvg": item.get("ratingAvg") or 0,
        "ratingCount": item.get("ratingCount") or 0,
    })


def discovery_material(item: dict[str, Any], *, reason: str | None = None) -> dict[str, Any]:
    tags = item.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    material_id = item.get("id") or item.get("materialId")
    uploader_display = item.get("uploaderNickname") or item.get("uploaderUsername") or item.get("uploaderDisplayName")
    return validate_discovery_material({
        "materialId": material_id,
        "title": item.get("title"),
        "summary": clamp_text(item.get("description"), max_length=DISCOVERY_SUMMARY_MAX_LENGTH),
        "school": item.get("school"),
        "college": item.get("college"),
        "major": item.get("major"),
        "courseCategory": item.get("courseCategory"),
        "gradeValue": item.get("gradeValue"),
        "tags": tags,
        "free": bool(item.get("free")),
        "price": item.get("price"),
        "ratingAvg": item.get("ratingAvg") or 0,
        "ratingCount": item.get("ratingCount") or 0,
        "downloadCount": item.get("downloadCount") or 0,
        "viewCount": item.get("viewCount") or 0,
        "uploaderDisplayName": uploader_display,
        "url": material_referral_url(material_id),
        "reason": reason,
    })


def public_request(item: dict[str, Any]) -> dict[str, Any]:
    return validate_public_request({
        "id": item.get("id"),
        "course": item.get("course"),
        "keyword": item.get("keyword"),
        "school": item.get("school"),
        "college": item.get("college"),
        "major": item.get("major"),
        "budget": item.get("budget"),
        "fundedAmount": item.get("fundedAmount"),
        "responseCount": item.get("responseCount") or 0,
        "status": item.get("status"),
        "createdAt": item.get("createdAt"),
    })


def public_market(item: dict[str, Any]) -> dict[str, Any]:
    return validate_public_market({
        "id": item.get("id"),
        "title": item.get("title"),
        "description": clamp_text(item.get("description")),
        "school": item.get("school"),
        "category": item.get("category"),
        "price": item.get("price"),
        "wantCount": item.get("wantCount") or 0,
        "status": item.get("status"),
    })
