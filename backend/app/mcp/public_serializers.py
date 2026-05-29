from __future__ import annotations

from typing import Any


MAX_TEXT_LENGTH = 1200


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
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "description": clamp_text(item.get("description")),
        "school": item.get("school"),
        "college": item.get("college"),
        "major": item.get("major"),
        "tags": item.get("tags") or [],
        "free": bool(item.get("free")),
        "downloadCount": item.get("downloadCount") or 0,
        "ratingAvg": item.get("ratingAvg") or 0,
        "ratingCount": item.get("ratingCount") or 0,
        "previewManifest": item.get("previewManifest"),
        "previewWatermarkEnabled": item.get("previewWatermarkEnabled"),
        "previewSource": item.get("previewSource"),
    }


def public_request(item: dict[str, Any]) -> dict[str, Any]:
    return {
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
    }


def public_market(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "description": clamp_text(item.get("description")),
        "school": item.get("school"),
        "category": item.get("category"),
        "price": item.get("price"),
        "wantCount": item.get("wantCount") or 0,
        "status": item.get("status"),
    }
