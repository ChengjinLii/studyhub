from __future__ import annotations

import json
from typing import Any


PUBLIC_BASE_URL = "https://study-hub.cn"


def json_text(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))


def material_url(material_id: int | str) -> str:
    return f"{PUBLIC_BASE_URL}/materials/{material_id}"


def request_url(request_id: int | str) -> str:
    return f"{PUBLIC_BASE_URL}/requests/{request_id}"


def market_url(item_id: int | str) -> str:
    return f"{PUBLIC_BASE_URL}/market/{item_id}"


def user_url(user_id: int | str) -> str:
    return f"{PUBLIC_BASE_URL}/u/{user_id}"


def material_result(item: dict[str, Any]) -> dict[str, Any]:
    material_id = item["id"]
    return {
        "id": f"material:{material_id}",
        "title": item.get("title") or f"资料 {material_id}",
        "url": material_url(material_id),
        "metadata": {
            "type": "material",
            "school": item.get("school"),
            "college": item.get("college"),
            "major": item.get("major"),
            "tags": item.get("tags") or [],
            "free": item.get("free"),
        },
    }


def request_result(item: dict[str, Any]) -> dict[str, Any]:
    request_id = item["id"]
    title = item.get("course") or item.get("keyword") or f"求购 {request_id}"
    return {
        "id": f"request:{request_id}",
        "title": title,
        "url": request_url(request_id),
        "metadata": {
            "type": "request",
            "school": item.get("school"),
            "college": item.get("college"),
            "major": item.get("major"),
            "budget": item.get("budget"),
            "status": item.get("status"),
        },
    }


def market_result(item: dict[str, Any]) -> dict[str, Any]:
    item_id = item["id"]
    return {
        "id": f"market:{item_id}",
        "title": item.get("title") or f"集市商品 {item_id}",
        "url": market_url(item_id),
        "metadata": {
            "type": "market",
            "school": item.get("school"),
            "category": item.get("category"),
            "price": item.get("price"),
            "status": item.get("status"),
        },
    }


def material_text(item: dict[str, Any]) -> str:
    lines = [
        f"# {item.get('title') or '资料'}",
        "",
        item.get("description") or "",
        "",
        f"- 学校: {item.get('school') or '-'}",
        f"- 学院: {item.get('college') or '-'}",
        f"- 专业: {item.get('major') or '-'}",
        f"- 标签: {', '.join(item.get('tags') or []) or '-'}",
        f"- 下载次数: {item.get('downloadCount') or 0}",
    ]
    return "\n".join(lines).strip()


def request_text(item: dict[str, Any]) -> str:
    lines = [
        f"# {item.get('course') or item.get('keyword') or '求购'}",
        "",
        f"- 关键词: {item.get('keyword') or '-'}",
        f"- 学校: {item.get('school') or '-'}",
        f"- 学院: {item.get('college') or '-'}",
        f"- 专业: {item.get('major') or '-'}",
        f"- 预算: {item.get('budget') if item.get('budget') is not None else '-'}",
        f"- 已筹: {item.get('fundedAmount') if item.get('fundedAmount') is not None else '-'}",
        f"- 状态: {item.get('status') or '-'}",
    ]
    return "\n".join(lines).strip()


def market_text(item: dict[str, Any]) -> str:
    lines = [
        f"# {item.get('title') or '集市商品'}",
        "",
        item.get("description") or "",
        "",
        f"- 学校: {item.get('school') or '-'}",
        f"- 分类: {item.get('category') or '-'}",
        f"- 价格: {item.get('price') if item.get('price') is not None else '-'}",
        f"- 想要人数: {item.get('wantCount') or 0}",
    ]
    return "\n".join(lines).strip()
