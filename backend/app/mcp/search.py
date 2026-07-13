from __future__ import annotations

from typing import Any

from app.api.deps import get_materials_service
from app.core.db import session_scope
from app.mcp.public_serializers import discovery_material
from app.mcp.serializers import public_base_url


def clamp_limit(limit: int | None, *, default: int = 5, max_value: int = 20) -> int:
    if limit is None:
        return default
    return max(1, min(int(limit), max_value))


def search_materials(
    query: str | None,
    limit: int | None,
    *,
    course: str | None = None,
    goal: str | None = None,
    material_type: str | None = None,
    school: str | None = None,
    college: str | None = None,
    major: str | None = None,
    tag: str | None = None,
) -> dict[str, Any]:
    del goal
    safe_limit = clamp_limit(limit)
    search_query = _join_search_context(course, query, material_type)
    with session_scope() as session:
        data = get_materials_service().list_materials(
            session,
            None,
            keyword=search_query,
            school=school,
            college=college,
            major=major,
            tag=tag,
            grade_value=None,
            course_category=None,
            price=None,
            sort="latest",
            page=1,
            size=safe_limit,
        )
    return {
        "items": [
            discovery_material(item, reason=_material_reason(item, search_query))
            for item in data.get("items") or []
        ],
        "meta": data.get("meta"),
        "message": "请打开返回的 StudyHub 资料详情链接完成登录、购买或下载；MCP 不提供文件或下载地址。",
    }


def material_detail(material_id: int) -> dict[str, Any]:
    with session_scope() as session:
        detail = get_materials_service().get_detail(session, None, material_id, False)
    return discovery_material(
        detail,
        reason="这是 StudyHub 公开资料详情。请打开返回的站内链接完成登录、购买或下载。",
    )


def public_material_recommendations(
    query: str | None = None,
    limit: int | None = 6,
    *,
    course: str | None = None,
    goal: str | None = None,
    time_budget: str | None = None,
    material_type: str | None = None,
    school: str | None = None,
    college: str | None = None,
    major: str | None = None,
) -> dict[str, Any]:
    safe_limit = clamp_limit(limit, default=6)
    search_query = _join_search_context(course, query, material_type)
    if search_query:
        discovered = search_materials(
            search_query,
            safe_limit,
            school=school,
            college=college,
            major=major,
        )
        raw_items = discovered.get("items") or []
        if not raw_items and course:
            broader_query = _join_search_context(course, material_type)
            if broader_query and broader_query != search_query:
                discovered = search_materials(
                    broader_query,
                    safe_limit,
                    school=school,
                    college=college,
                    major=major,
                )
                raw_items = discovered.get("items") or []
        items = [
            _with_recommendation_context(item, goal=goal, time_budget=time_budget)
            for item in raw_items
        ]
        return {
            "items": items,
            "message": (
                "这些是基于公开资料目录的推荐。请打开 StudyHub 链接完成后续查看或下载。"
                if items
                else "暂未找到与当前课程和目标足够相关的公开资料；可以调整课程名称或资料类型后重试。"
            ),
        }
    with session_scope() as session:
        items = get_materials_service().get_recommendations(session, None, safe_limit)
    return {
        "items": [
            _with_recommendation_context(
                discovery_material(item, reason=_material_reason(item, search_query)),
                goal=goal,
                time_budget=time_budget,
            )
            for item in items
        ],
        "message": "这些是基于公开资料目录的推荐。请打开 StudyHub 链接完成后续查看或下载。",
    }


def platform_policy(question: str) -> dict[str, Any]:
    normalized = str(question or "").strip().lower()
    policies = [
        {
            "topic": "资料上传与审核",
            "summary": "投稿者应拥有合法分享权，并如实填写资料信息；资料需经过平台审核后公开展示。",
            "url": _site_url("/upload"),
            "signals": ("上传", "投稿", "审核", "版权", "侵权"),
        },
        {
            "topic": "资料获取与下载",
            "summary": "资料获取、登录校验、积分或付费判断以及下载配额均在 StudyHub 站内完成；MCP 不返回文件和下载链接。",
            "url": _site_url("/materials"),
            "signals": ("下载", "获取", "积分", "配额", "免费"),
        },
        {
            "topic": "付费与退款",
            "summary": "付费资料必须通过 StudyHub 站内订单和支付流程处理，不应通过外部 Agent 绕过订单、支付或结算规则。",
            "url": _site_url("/materials"),
            "signals": ("支付", "付费", "价格", "退款", "订单", "结算"),
        },
        {
            "topic": "账号与隐私",
            "summary": "登录态和个人数据仅用于获得用户授权的站内功能；外部 Agent 只能在获授 OAuth scope 范围内调用 MCP。",
            "url": _site_url("/login"),
            "signals": ("登录", "账号", "隐私", "oauth", "授权"),
        },
    ]
    matched = [item for item in policies if any(signal in normalized for signal in item["signals"])]
    selected = matched or policies
    return {
        "question": str(question or "").strip()[:500],
        "policies": [{key: value for key, value in item.items() if key != "signals"} for item in selected],
        "url": _site_url("/more"),
        "message": "规则可能随平台更新，请以返回的 StudyHub 页面和站内实际流程为准。",
    }


def _material_reason(item: dict[str, Any], query: str | None) -> str:
    title = item.get("title") or "这份资料"
    tags = item.get("tags") if isinstance(item.get("tags"), list) else []
    if query and str(query).strip():
        return f"《{title}》与“{str(query).strip()}”的检索意图相近，建议打开 StudyHub 链接查看详情。"
    if tags:
        return f"这份资料包含 {' / '.join(str(tag) for tag in tags[:3])} 等标签，适合作为公开目录推荐候选。"
    return "这是 StudyHub 公开资料目录中的推荐候选，请打开站内链接查看详情。"


def _join_search_context(*values: str | None) -> str:
    parts: list[str] = []
    for value in values:
        text = " ".join(str(value or "").split()).strip()
        if text and text not in parts:
            parts.append(text[:160])
    return " ".join(parts)[:500]


def _with_recommendation_context(
    item: dict[str, Any],
    *,
    goal: str | None,
    time_budget: str | None,
) -> dict[str, Any]:
    reason_parts = [str(item.get("reason") or "").rstrip("。")]
    clean_goal = " ".join(str(goal or "").split()).strip()[:120]
    clean_budget = " ".join(str(time_budget or "").split()).strip()[:120]
    if clean_goal:
        reason_parts.append(f"适合围绕“{clean_goal}”进一步判断")
    if clean_budget:
        reason_parts.append(f"可结合“{clean_budget}”安排使用顺序")
    return {**item, "reason": "；".join(part for part in reason_parts if part) + "。"}


def _site_url(path: str) -> str:
    return f"{public_base_url()}{path}"
