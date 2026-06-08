from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.materials import MaterialRecord
from app.repos.auth_repo import AuthRepository
from app.repos.material_repo import MaterialRepository
from app.services.agent_material_signal_service import build_material_signals
from app.services.material_pdf_evidence_service import MaterialPageEvidence


MEMORY_SIGNAL_TERMS = (
    "真题",
    "往年",
    "历年",
    "期末",
    "期中",
    "题型",
    "解析",
    "答案",
    "速成",
    "笔记",
    "讲义",
    "复习",
    "经验",
    "经验分享",
    "攻略",
    "面经",
    "刷题",
    "错题",
    "实验",
    "报告",
)

STUDY_STRATEGY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("先建立知识框架", ("知识框架", "建立框架", "先看课件", "先看讲义", "先过一遍")),
    ("按题型训练", ("按题型", "题型整理", "题型归纳", "分类刷题")),
    ("刷真题", ("刷真题", "做真题", "往年题", "历年题", "期末题")),
    ("对答案解析", ("对答案", "看解析", "答案解析", "自制解析", "参考答案")),
    ("复盘错题", ("错题", "复盘", "错因", "查漏补缺")),
    ("冲刺速成", ("速成", "冲刺", "考前", "提纲", "重点背诵")),
    ("经验参考", ("经验分享", "经验贴", "攻略", "面经", "避坑")),
)


@dataclass(slots=True)
class AgentMemoryContext:
    platform: dict[str, Any]
    user: dict[str, Any] | None

    def is_empty(self) -> bool:
        return not self.platform and not self.user

    def to_prompt_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.platform:
            payload["platform_collective_memory"] = self.platform
        if self.user:
            payload["user_personal_memory"] = self.user
        return payload


class AgentMemoryService:
    """Read-only memory context builder for the StudyHub Agent.

    This version intentionally does not persist memory. It derives compact,
    bounded context from existing candidate materials, PDF evidence, and the
    current user's own profile/interactions so the Agent can behave more
    personally without changing database schema or frontend flow.
    """

    def __init__(self, settings: Settings, auth_repo: AuthRepository, material_repo: MaterialRepository) -> None:
        self.settings = settings
        self.auth_repo = auth_repo
        self.material_repo = material_repo

    def collect(
        self,
        session: Session,
        *,
        query: str,
        materials: list[MaterialRecord],
        current_user_id: int | None,
        pdf_evidence: list[MaterialPageEvidence],
    ) -> AgentMemoryContext:
        if not self.settings.ai_agent_memory_context_enabled:
            return AgentMemoryContext(platform={}, user=None)
        limited_materials = materials[: max(0, int(self.settings.ai_agent_memory_max_materials or 0))]
        platform = self._build_platform_memory(query, limited_materials, pdf_evidence)
        user = self._build_user_memory(session, limited_materials, current_user_id)
        return AgentMemoryContext(platform=platform, user=user)

    def _build_platform_memory(
        self,
        query: str,
        materials: list[MaterialRecord],
        pdf_evidence: list[MaterialPageEvidence],
    ) -> dict[str, Any]:
        if not materials and not pdf_evidence:
            return {}
        tag_counter: Counter[str] = Counter()
        course_counter: Counter[str] = Counter()
        school_counter: Counter[str] = Counter()
        signal_counter: Counter[str] = Counter()
        material_quality_counter: Counter[str] = Counter()
        material_risk_counter: Counter[str] = Counter()
        study_strategy_counter: Counter[str] = Counter()
        year_counter: Counter[str] = Counter()
        question_type_counter: Counter[str] = Counter()
        question_number_counter: Counter[str] = Counter()
        score_point_counter: Counter[str] = Counter()
        difficulty_counter: Counter[str] = Counter()
        visual_counter: Counter[str] = Counter()
        source_type_counter: Counter[str] = Counter()
        for material in materials:
            tag_counter.update(_json_string_list(material.tags_json))
            for value in (material.major, material.college, material.course_category, material.grade_value):
                if value:
                    course_counter.update([str(value).strip()])
            if material.school:
                school_counter.update([material.school.strip()])
            material_text = _material_text(material)
            signal_counter.update(_signal_terms(material_text))
            study_strategy_counter.update(_study_strategy_terms(material_text))
            material_signals = build_material_signals(material)
            material_quality_counter.update(material_signals.quality_signals)
            material_risk_counter.update(material_signals.risk_signals)
        for item in pdf_evidence:
            signal_counter.update(_signal_terms(item.text))
            year_counter.update(item.years)
            question_type_counter.update(item.question_types)
            question_number_counter.update(item.question_numbers)
            score_point_counter.update(str(value) for value in item.score_points)
            difficulty_counter.update(item.difficulty_signals)
            visual_counter.update(item.visual_signals)
            if item.source_type != "unknown":
                source_type_counter.update([item.source_type])
        top_materials = [
            _high_signal_material_payload(material)
            for material in sorted(
                materials,
                key=lambda item: (
                    -int(item.download_count or 0),
                    -build_material_signals(item).quality_score,
                    -float(item.rating_avg or 0),
                    -int(item.like_count or 0),
                    int(item.id),
                ),
            )[:3]
        ]
        payload: dict[str, Any] = {
            "query_focus": _compact_query_focus(query),
            "candidate_count": len(materials),
            "top_tags": _counter_items(tag_counter, limit=6),
            "course_signals": _counter_items(course_counter, limit=5),
            "school_signals": _counter_items(school_counter, limit=3),
            "question_type_signals": _counter_items(signal_counter, limit=6),
            "study_strategy_signals": _counter_items(study_strategy_counter, limit=8),
            "material_quality_signals": _counter_items(material_quality_counter, limit=8),
            "material_risk_signals": _counter_items(material_risk_counter, limit=8),
            "pdf_year_signals": _counter_items(year_counter, limit=6),
            "pdf_question_type_signals": _counter_items(question_type_counter, limit=6),
            "pdf_question_number_signals": _counter_items(question_number_counter, limit=8),
            "pdf_score_point_signals": _counter_items(score_point_counter, limit=8),
            "pdf_difficulty_signals": _counter_items(difficulty_counter, limit=5),
            "pdf_visual_signals": _counter_items(visual_counter, limit=5),
            "pdf_source_type_signals": _counter_items(source_type_counter, limit=5),
            "high_signal_materials": top_materials,
            "experience_materials": _experience_material_payloads(materials),
            "pdf_evidence_pages": [
                _evidence_page_payload(item)
                for item in pdf_evidence[: max(0, int(self.settings.ai_agent_pdf_evidence_max_pages or 0))]
            ],
            "privacy_boundary": "Only aggregate platform signals are included here; no individual user profile or private conversation is mixed into collective memory.",
        }
        return {key: value for key, value in payload.items() if value not in (None, [], {}, "")}

    def _build_user_memory(
        self,
        session: Session,
        materials: list[MaterialRecord],
        current_user_id: int | None,
    ) -> dict[str, Any] | None:
        if current_user_id is None:
            return None
        try:
            user = self.auth_repo.find_user_by_id(session, current_user_id)
        except Exception:
            return None
        if user is None:
            return None
        profile = _user_profile_payload(user)
        matched_candidates = self._matched_candidate_payloads(materials, profile)
        interactions = self._candidate_interaction_payloads(session, materials, current_user_id)
        preferences = self._preference_payload(materials, interactions)
        payload: dict[str, Any] = {
            "profile": profile,
            "matched_candidate_materials": matched_candidates,
            "candidate_interactions": interactions,
            "inferred_preferences": preferences,
            "privacy_boundary": "This personal memory belongs only to the current authenticated user and must not be written into platform collective memory.",
        }
        return {key: value for key, value in payload.items() if value not in (None, [], {}, "")}

    def _matched_candidate_payloads(self, materials: list[MaterialRecord], profile: dict[str, str]) -> list[dict[str, Any]]:
        matched: list[dict[str, Any]] = []
        for material in materials:
            fields = []
            if profile.get("school") and material.school == profile["school"]:
                fields.append("school")
            if profile.get("college") and material.college == profile["college"]:
                fields.append("college")
            if profile.get("major") and material.major and profile["major"] in material.major:
                fields.append("major")
            if not fields:
                continue
            matched.append({"material_id": int(material.id), "title": material.title, "matched_fields": fields})
            if len(matched) >= 5:
                break
        return matched

    def _candidate_interaction_payloads(
        self,
        session: Session,
        materials: list[MaterialRecord],
        current_user_id: int,
    ) -> list[dict[str, Any]]:
        interactions: list[dict[str, Any]] = []
        for material in materials[: max(0, int(self.settings.ai_agent_memory_max_interaction_checks or 0))]:
            flags: list[str] = []
            try:
                if self.material_repo.find_favorite(session, int(material.id), current_user_id) is not None:
                    flags.append("favorited")
                if self.material_repo.has_download(session, int(material.id), current_user_id):
                    flags.append("downloaded")
                if self.material_repo.has_purchase(session, int(material.id), current_user_id):
                    flags.append("purchased")
                rating = self.material_repo.find_rating(session, int(material.id), current_user_id)
            except Exception:
                rating = None
            if rating is not None:
                flags.append(f"rated_{int(rating.rating)}")
            if int(material.uploader_id or 0) == current_user_id:
                flags.append("uploaded_by_user")
            if flags:
                interactions.append({"material_id": int(material.id), "title": material.title, "signals": flags})
        return interactions

    def _preference_payload(self, materials: list[MaterialRecord], interactions: list[dict[str, Any]]) -> dict[str, Any]:
        interacted_ids = {int(item["material_id"]) for item in interactions if item.get("material_id") is not None}
        if not interacted_ids:
            return {}
        tag_counter: Counter[str] = Counter()
        type_counter: Counter[str] = Counter()
        for material in materials:
            if int(material.id) not in interacted_ids:
                continue
            tag_counter.update(_json_string_list(material.tags_json))
            type_counter.update(_signal_terms(_material_text(material)))
        payload = {
            "preferred_tags_from_existing_actions": _counter_items(tag_counter, limit=5),
            "preferred_content_types_from_existing_actions": _counter_items(type_counter, limit=5),
        }
        return {key: value for key, value in payload.items() if value}


def _high_signal_material_payload(material: MaterialRecord) -> dict[str, Any]:
    material_signals = build_material_signals(material)
    payload: dict[str, Any] = {
        "material_id": int(material.id),
        "title": material.title,
        "downloads": int(material.download_count or 0),
        "rating_avg": float(material.rating_avg or 0),
        "tags": _json_string_list(material.tags_json)[:4],
    }
    if material_signals.quality_score:
        payload["quality_score"] = material_signals.quality_score
    if material_signals.quality_signals:
        payload["quality_signals"] = list(material_signals.quality_signals[:4])
    if material_signals.risk_signals:
        payload["risk_signals"] = list(material_signals.risk_signals[:4])
    return payload


def _experience_material_payloads(materials: list[MaterialRecord]) -> list[dict[str, Any]]:
    matched = [material for material in materials if _looks_like_experience_material(material)]
    matched.sort(
        key=lambda item: (
            -build_material_signals(item).quality_score,
            -int(item.download_count or 0),
            -float(item.rating_avg or 0),
            -int(item.like_count or 0),
            int(item.id),
        )
    )
    payloads: list[dict[str, Any]] = []
    for material in matched[:4]:
        material_signals = build_material_signals(material)
        payload: dict[str, Any] = {
            "material_id": int(material.id),
            "title": material.title,
            "tags": _json_string_list(material.tags_json)[:4],
        }
        strategy_terms = _study_strategy_terms(_material_text(material))
        if strategy_terms:
            payload["study_strategy_signals"] = strategy_terms[:4]
        if material_signals.quality_signals:
            payload["quality_signals"] = list(material_signals.quality_signals[:3])
        payloads.append(payload)
    return payloads


def _user_profile_payload(user: Any) -> dict[str, str]:
    payload = {
        "school": _clean_text(getattr(user, "school", None)),
        "college": _clean_text(getattr(user, "college", None)),
        "major": _clean_text(getattr(user, "major", None)),
        "grade_stages": _clean_text(getattr(user, "grade_stages", None)),
    }
    return {key: value for key, value in payload.items() if value}


def _evidence_page_payload(item: MaterialPageEvidence) -> dict[str, Any]:
    payload: dict[str, Any] = {"material_id": item.material_id, "title": item.title, "page": item.page}
    if item.question_numbers:
        payload["question_numbers"] = list(item.question_numbers)
    if item.score_points:
        payload["score_points"] = list(item.score_points)
    if item.difficulty_signals:
        payload["difficulty_signals"] = list(item.difficulty_signals)
    if item.visual_signals:
        payload["visual_signals"] = list(item.visual_signals)
    if item.anchor_terms:
        payload["anchor_terms"] = list(item.anchor_terms)
    if item.anchor_text:
        payload["anchor_text"] = item.anchor_text
    if item.source_type != "unknown":
        payload["source_type"] = item.source_type
    return payload


def _json_string_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [_clean_text(item) for item in parsed if _clean_text(item)]


def _material_text(material: MaterialRecord) -> str:
    return " ".join(
        value
        for value in [
            _clean_text(material.title),
            _clean_text(material.description),
            _clean_text(material.keywords),
            " ".join(_json_string_list(material.tags_json)),
        ]
        if value
    )


def _signal_terms(text: str) -> list[str]:
    normalized = text.lower()
    return [term for term in MEMORY_SIGNAL_TERMS if term.lower() in normalized]


def _study_strategy_terms(text: str) -> list[str]:
    normalized = text.lower()
    result: list[str] = []
    for label, aliases in STUDY_STRATEGY_PATTERNS:
        if any(alias.lower() in normalized for alias in aliases) and label not in result:
            result.append(label)
    return result[:8]


def _looks_like_experience_material(material: MaterialRecord) -> bool:
    text = _material_text(material)
    tags = _json_string_list(material.tags_json)
    if any(tag in {"经验", "经验分享", "攻略", "面经"} for tag in tags):
        return True
    return bool({"经验参考", "复盘错题", "冲刺速成"} & set(_study_strategy_terms(text)))


def _compact_query_focus(query: str) -> list[str]:
    terms = [_clean_text(item) for item in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", query)]
    result: list[str] = []
    for term in terms:
        if len(term) < 2 or term in result:
            continue
        result.append(term)
        if len(result) >= 8:
            break
    return result


def _counter_items(counter: Counter[str], *, limit: int) -> list[dict[str, Any]]:
    return [{"value": value, "count": count} for value, count in counter.most_common(limit) if value]


def _clean_text(value: Any, *, max_chars: int = 80) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()[:max_chars]
