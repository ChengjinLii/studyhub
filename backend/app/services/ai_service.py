from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.materials import MaterialRecord
from app.repos.material_repo import MaterialRepository
from app.repos.read_api_repo import ReadApiRepository
from app.schemas.ai import AiChatRequestPayload, AiRecommendRequestPayload
from app.services.read_support import parse_iso_datetime


class AiService:
    """本地兼容层只负责维持现有请求/响应契约，不在 Step 10 引入外部 AI 依赖。"""

    def __init__(self, read_repo: ReadApiRepository, material_repo: MaterialRepository) -> None:
        self.read_repo = read_repo
        self.material_repo = material_repo

    def chat(self, payload: AiChatRequestPayload) -> dict[str, Any]:
        latest_user_message = next((item.content.strip() for item in reversed(payload.messages) if item.role.lower() == "user"), "")
        if not latest_user_message:
            latest_user_message = payload.messages[-1].content.strip()
        content = (
            "当前为 StudyHub FastAPI 本地兼容回复。\n"
            f"你的问题是：{latest_user_message}\n"
            "Step 10 先保证接口契约、鉴权和错误语义稳定；真正的外部模型接入放到后续环境配置阶段。"
        )
        return {"content": content}

    def recommend(self, session: Session, payload: AiRecommendRequestPayload) -> dict[str, Any]:
        materials = self._rank_materials(session, payload.query, payload.filters or {})
        recommendations = []
        for material in materials[:3]:
            recommendations.append(
                {
                    "material_id": material.id,
                    "title": material.title,
                    "tags": self._loads(material.tags_json),
                    "reason": self._build_reason(material, payload.query),
                    "summary": material.description,
                }
            )
        body = {
            "recommendations": recommendations,
            "followup_questions": [
                "你更想要真题、笔记还是经验分享？",
                "是否需要限定学校、学院或专业？",
            ],
        }
        return {"output": f"<json>{json.dumps(body, ensure_ascii=False, separators=(',', ':'))}</json>"}

    def _rank_materials(self, session: Session, query: str, filters: dict[str, Any]) -> list[MaterialRecord]:
        seed = self.read_repo.load_seed()
        self.material_repo.ensure_seed_bootstrap(session, seed)
        normalized_query = query.strip().lower()
        school = str(filters.get("school")).strip() if filters.get("school") else None
        major = str(filters.get("major")).strip() if filters.get("major") else None
        items = self.material_repo.list_visible_materials(session)
        items.sort(
            key=lambda item: (
                -self._score(item, normalized_query, school=school, major=major),
                -int(item.download_count or 0),
                -parse_iso_datetime(item.created_at.isoformat() if item.created_at else None).timestamp(),
            )
        )
        return items

    def _score(self, material: MaterialRecord, query: str, *, school: str | None, major: str | None) -> int:
        haystack = " ".join(
            [
                material.title or "",
                material.description or "",
                material.original_filename or "",
                " ".join(self._loads(material.tags_json)),
                material.school or "",
                material.college or "",
                material.major or "",
            ]
        ).lower()
        score = 0
        for token in [item for item in query.split() if item]:
            if token in haystack:
                score += 5
        if query and query in haystack:
            score += 10
        if school and material.school == school:
            score += 3
        if major and material.major == major:
            score += 4
        return score

    def _build_reason(self, material: MaterialRecord, query: str) -> str:
        parts = []
        if material.school:
            parts.append(f"同校资料：{material.school}")
        if material.major:
            parts.append(f"专业匹配：{material.major}")
        if query and query.lower() in ((material.title or "") + " " + (material.description or "")).lower():
            parts.append("标题或简介直接命中你的关键词")
        if not parts:
            parts.append("下载量和内容完整度在当前候选中更靠前")
        return "；".join(parts)

    def _loads(self, value: str | None) -> list[str]:
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return [str(item) for item in parsed if isinstance(item, (str, int, float))]
