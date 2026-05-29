from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.api.deps import (
    get_health_service,
    get_leaderboard_read_service,
    get_market_service,
    get_materials_service,
    get_requests_service,
)
from app.core.db import session_scope
from app.mcp.public_serializers import public_market, public_material, public_request
from app.mcp.serializers import (
    json_text,
    market_result,
    market_text,
    market_url,
    material_result,
    material_text,
    material_url,
    request_result,
    request_text,
    request_url,
)


def clamp_limit(limit: int | None, *, default: int = 5, max_value: int = 20) -> int:
    if limit is None:
        return default
    return max(1, min(int(limit), max_value))


def search_materials(query: str | None, limit: int | None) -> dict[str, Any]:
    safe_limit = clamp_limit(limit)
    with session_scope() as session:
        data = get_materials_service().list_materials(
            session,
            None,
            keyword=query,
            school=None,
            college=None,
            major=None,
            tag=None,
            grade_value=None,
            course_category=None,
            price=None,
            sort="latest",
            page=1,
            size=safe_limit,
        )
    return data


def material_detail(material_id: int) -> dict[str, Any]:
    with session_scope() as session:
        detail = get_materials_service().get_detail(session, None, material_id, False)
    return public_material(detail)


def material_preview(material_id: int) -> dict[str, Any]:
    detail = material_detail(material_id)
    return {
        "id": detail.get("id"),
        "title": detail.get("title"),
        "description": detail.get("description"),
        "previewManifest": detail.get("previewManifest"),
        "customPreviewText": detail.get("customPreviewText"),
        "customPreviewImages": detail.get("customPreviewImages") or [],
    }


def material_recommendations(limit: int | None) -> dict[str, Any]:
    with session_scope() as session:
        items = get_materials_service().get_recommendations(session, None, clamp_limit(limit))
    return {"items": items}


def search_requests(query: str | None, limit: int | None) -> dict[str, Any]:
    safe_limit = clamp_limit(limit)
    source_limit = 100 if query else safe_limit
    with session_scope() as session:
        items = get_requests_service().list_requests(session, None, sort="hot", limit=source_limit)
    if query:
        filtered = [item for item in items if _matches_text(item, query)]
        if not filtered:
            return {"items": [], "message": "未找到相关求购"}
        items = filtered
    return {"items": [public_request(item) for item in items[:safe_limit]]}


def request_detail(request_id: int) -> dict[str, Any]:
    with session_scope() as session:
        detail = get_requests_service().get_detail(session, 0, None, request_id)
    return public_request(detail)


def request_leaderboard(limit: int | None) -> dict[str, Any]:
    safe_limit = clamp_limit(limit)
    with session_scope() as session:
        items = get_requests_service().list_leaderboard(session, None, limit=safe_limit)
    return {"items": [public_request(item) for item in items]}


def search_market(query: str | None, limit: int | None) -> dict[str, Any]:
    safe_limit = clamp_limit(limit)
    with session_scope() as session:
        data = get_market_service().list_market(session, None, keyword=query, category=None, page=1, size=safe_limit)
    if query and not data.get("items"):
        return {"items": [], "meta": data.get("meta"), "stats": data.get("stats"), "message": "未找到相关集市商品"}
    data["items"] = [public_market(item) for item in data.get("items") or []]
    return data


def market_detail(item_id: int) -> dict[str, Any]:
    with session_scope() as session:
        detail = get_market_service().get_detail(session, None, item_id)
    return public_market(detail)


def contributor_leaderboard(limit: int | None, period: str | None) -> dict[str, Any]:
    with session_scope() as session:
        items = get_leaderboard_read_service().get_contributors(session, clamp_limit(limit, default=20, max_value=100), period)
    return {"items": items}


def health_ready() -> dict[str, Any]:
    with session_scope() as session:
        return get_health_service().build_readiness_payload(session, deep=False)


def search_all(query: str, limit: int | None) -> dict[str, Any]:
    per_kind = max(1, clamp_limit(limit, default=9) // 3)
    materials = search_materials(query, per_kind).get("items") or []
    requests = search_requests(query, per_kind).get("items") or []
    market = search_market(query, per_kind).get("items") or []

    if query and not requests:
        requests = []
    if query and not market:
        market = []

    results = [material_result(item) for item in materials[:per_kind]]
    results.extend(request_result(item) for item in requests[:per_kind])
    results.extend(market_result(item) for item in market[:per_kind])
    return {"results": results[: clamp_limit(limit, default=9)]}


def fetch_typed(resource_id: str) -> dict[str, Any]:
    kind, raw_id = parse_typed_id(resource_id)
    item_id = int(raw_id)
    if kind == "material":
        detail = material_detail(item_id)
        return {
            "id": resource_id,
            "title": detail.get("title") or f"资料 {item_id}",
            "text": material_text(detail),
            "url": material_url(item_id),
            "metadata": {"type": "material", "public": detail},
        }
    if kind == "request":
        detail = request_detail(item_id)
        return {
            "id": resource_id,
            "title": detail.get("course") or detail.get("keyword") or f"求购 {item_id}",
            "text": request_text(detail),
            "url": request_url(item_id),
            "metadata": {"type": "request", "public": detail},
        }
    if kind == "market":
        detail = market_detail(item_id)
        return {
            "id": resource_id,
            "title": detail.get("title") or f"集市商品 {item_id}",
            "text": market_text(detail),
            "url": market_url(item_id),
            "metadata": {"type": "market", "public": detail},
        }
    raise HTTPException(status_code=400, detail=f"Unsupported fetch id: {resource_id}")


def parse_typed_id(resource_id: str) -> tuple[str, str]:
    if ":" not in resource_id:
        raise HTTPException(status_code=400, detail="fetch id must use '<type>:<id>' format")
    kind, raw_id = resource_id.split(":", 1)
    if kind not in {"material", "request", "market", "user"}:
        raise HTTPException(status_code=400, detail=f"Unsupported fetch type: {kind}")
    if not raw_id.isdigit():
        raise HTTPException(status_code=400, detail="fetch id must end with a numeric id")
    return kind, raw_id


def as_text_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json_text(payload)}], "structuredContent": payload}


def _matches_text(item: dict[str, Any], query: str) -> bool:
    needle = query.strip().lower()
    if not needle:
        return True
    haystack = json_text(item).lower()
    return needle in haystack
