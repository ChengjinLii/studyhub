from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx


SAFE_MATERIAL_FIELDS = {
    "id",
    "materialId",
    "title",
    "description",
    "school",
    "college",
    "major",
    "courseCategory",
    "gradeValue",
    "tags",
    "free",
    "price",
    "ratingAvg",
    "ratingCount",
    "downloadCount",
    "viewCount",
    "uploaderDisplayName",
    "uploaderNickname",
    "uploaderUsername",
    "url",
    "reason",
}


@dataclass(slots=True)
class MaterialReferral:
    material_id: str
    title: str
    url: str
    reason: str
    free: bool
    price: int | float | None
    school: str | None = None
    college: str | None = None
    tags: tuple[str, ...] = ()
    download_count: int = 0
    rating_avg: float = 0


class StudyHubClient:
    def __init__(
        self,
        *,
        base_url: str,
        public_site_base_url: str,
        timeout_seconds: float = 8.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.public_site_base_url = public_site_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._client = http_client

    def recommend_materials(self, *, query: str | None, limit: int) -> list[MaterialReferral]:
        items = self._search_materials(query=query, limit=limit) if query else []
        if not items:
            items = self._public_recommendations(limit=limit)
        return [self._to_referral(item, query=query) for item in items[:limit]]

    def _search_materials(self, *, query: str | None, limit: int) -> list[dict[str, Any]]:
        params = {
            "keyword": query or "",
            "page": "1",
            "size": str(limit),
            "sort": "latest",
        }
        payload = self._get_json(f"/api/materials?{urlencode(params)}")
        data = payload.get("data") if isinstance(payload, dict) else {}
        items = data.get("items") if isinstance(data, dict) else []
        return [_safe_material(item) for item in items if isinstance(item, dict)]

    def _public_recommendations(self, *, limit: int) -> list[dict[str, Any]]:
        payload = self._get_json(f"/api/materials/recommendations?{urlencode({'limit': str(limit)})}")
        data = payload.get("data") if isinstance(payload, dict) else {}
        items = data if isinstance(data, list) else data.get("items") if isinstance(data, dict) else []
        return [_safe_material(item) for item in items if isinstance(item, dict)]

    def _get_json(self, path: str) -> dict[str, Any]:
        client = self._client or httpx.Client(timeout=self.timeout_seconds, trust_env=False)
        close_client = self._client is None
        try:
            response = client.get(f"{self.base_url}{path}")
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {}
        finally:
            if close_client:
                client.close()

    def _to_referral(self, item: dict[str, Any], *, query: str | None) -> MaterialReferral:
        material_id = str(item.get("materialId") or item.get("id") or "").strip()
        title = _clean_text(item.get("title"), fallback=f"StudyHub 资料 {material_id or '-'}", max_length=80)
        tags = tuple(str(tag).strip() for tag in (item.get("tags") or []) if str(tag).strip())[:3]
        url = str(item.get("url") or "").strip() or self._material_url(material_id)
        reason = _clean_text(item.get("reason"), fallback=_fallback_reason(title, query, tags), max_length=90)
        return MaterialReferral(
            material_id=material_id,
            title=title,
            url=url,
            reason=reason,
            free=bool(item.get("free")),
            price=item.get("price"),
            school=_clean_optional(item.get("school"), max_length=24),
            college=_clean_optional(item.get("college"), max_length=24),
            tags=tags,
            download_count=_safe_int(item.get("downloadCount")),
            rating_avg=_safe_float(item.get("ratingAvg")),
        )

    def _material_url(self, material_id: str) -> str:
        return f"{self.public_site_base_url}/materials/{material_id}?ref=qq_bot"


def _safe_material(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key in SAFE_MATERIAL_FIELDS}


def _clean_text(value: Any, *, fallback: str, max_length: int) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        text = fallback
    text = " ".join(text.split())
    return text if len(text) <= max_length else f"{text[: max_length - 1].rstrip()}..."


def _clean_optional(value: Any, *, max_length: int) -> str | None:
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    text = " ".join(text.split())
    return text if len(text) <= max_length else f"{text[: max_length - 1].rstrip()}..."


def _fallback_reason(title: str, query: str | None, tags: tuple[str, ...]) -> str:
    if query:
        return f"《{title}》和“{query}”相关，可以打开链接查看详情。"
    if tags:
        return f"标签包含 {' / '.join(tags)}，适合作为公开目录推荐。"
    return "这是 StudyHub 公开目录中的推荐资料。"


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0

