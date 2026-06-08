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

QUERY_WEAKNESS_TERMS = (
    "调制",
    "解调",
    "频谱",
    "带宽",
    "误码率",
    "匹配滤波",
    "判决",
    "信噪比",
    "傅里叶",
    "卷积",
    "链表",
    "二叉树",
    "排序",
    "积分",
    "微分",
    "极限",
    "概率",
    "分布",
)

QUERY_STUDY_TIME_PHRASES: tuple[tuple[str, int], ...] = (
    ("明天", 1),
    ("后天", 2),
    ("半个月", 15),
    ("一周", 7),
    ("二周", 14),
    ("两周", 14),
    ("三周", 21),
    ("四周", 28),
    ("一个月", 30),
    ("一月", 30),
)

QUERY_PROBLEM_FOCUS_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("概念理解", ("概念", "为什么", "不懂", "理解不了", "看不懂")),
    ("公式推导", ("公式", "推导", "证明", "怎么推", "推不出")),
    ("计算步骤", ("计算", "步骤", "怎么算", "怎么做", "代入", "求解", "不会做")),
    ("读题定位", ("题干", "条件", "读题", "问什么", "看不懂题")),
    ("答案复盘", ("解析", "答案", "错题", "哪里错", "对答案")),
)

QUERY_LEARNING_PREFERENCE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("补基础优先", ("基础差", "零基础", "基础不好", "基础不太好", "基础弱", "看不懂", "听不懂", "入门", "从零开始")),
    ("考前冲刺", ("速成", "冲刺", "考前", "短期", "来不及", "临时抱佛脚")),
    ("刷题优先", ("刷题", "真题", "练习", "做题", "套卷", "题海")),
    ("详细解析", ("详细解析", "一步步", "讲清楚", "讲明白", "细讲", "详细讲", "详细说明")),
    ("查漏补缺", ("查漏补缺", "错题", "薄弱", "短板", "弱项", "不会的地方")),
)

MATERIAL_COURSE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("电子系统设计", ("电子系统设计", "esd")),
    ("通信原理", ("通信原理", "cps")),
    ("信号与系统", ("信号与系统", "signals", "signal")),
    ("数据结构", ("数据结构",)),
    ("高等数学", ("高等数学", "高数", "微积分")),
    ("概率论", ("概率论",)),
)

MATERIAL_SOURCE_TYPE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("past_exam", ("真题", "往年", "历年", "试卷", "期末题", "样卷", "考题")),
    ("answer_explanation", ("解析", "答案", "标答", "参考答案", "讲解")),
    ("lecture_notes", ("笔记", "讲义", "导图", "课件")),
    ("study_outline", ("速成", "提纲", "复习", "冲刺")),
    ("experience", ("经验", "经验分享", "经验贴", "攻略", "面经")),
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
        user = self._build_user_memory(session, query, limited_materials, current_user_id)
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
        material_source_type_counter: Counter[str] = Counter()
        study_strategy_counter: Counter[str] = Counter()
        year_counter: Counter[str] = Counter()
        question_type_counter: Counter[str] = Counter()
        chapter_counter: Counter[str] = Counter()
        solution_counter: Counter[str] = Counter()
        question_number_counter: Counter[str] = Counter()
        score_point_counter: Counter[str] = Counter()
        difficulty_counter: Counter[str] = Counter()
        visual_counter: Counter[str] = Counter()
        source_type_counter: Counter[str] = Counter()
        for material in materials:
            tag_counter.update(_json_string_list(material.tags_json))
            for value in (material.major, material.college, material.course_category, material.grade_value):
                cleaned = _clean_memory_text(value)
                if cleaned:
                    course_counter.update([cleaned])
            if material.school:
                cleaned_school = _clean_memory_text(material.school)
                if cleaned_school:
                    school_counter.update([cleaned_school])
            material_text = _material_text(material)
            signal_counter.update(_signal_terms(material_text))
            course_counter.update(_material_course_terms(material_text))
            material_source_type_counter.update(_material_source_type_terms(material_text))
            study_strategy_counter.update(_study_strategy_terms(material_text))
            material_signals = build_material_signals(material)
            material_quality_counter.update(material_signals.quality_signals)
            material_risk_counter.update(material_signals.risk_signals)
        for item in pdf_evidence:
            signal_counter.update(_signal_terms(_clean_memory_text(item.text, max_chars=240)))
            year_counter.update(_memory_values(item.years))
            question_type_counter.update(_memory_values(item.question_types))
            chapter_counter.update(_memory_values(item.chapter_signals))
            solution_counter.update(_memory_values(item.solution_signals))
            question_number_counter.update(_memory_values(item.question_numbers))
            score_point_counter.update(_memory_values(str(value) for value in item.score_points))
            difficulty_counter.update(_memory_values(item.difficulty_signals))
            visual_counter.update(_memory_values(item.visual_signals))
            if item.source_type != "unknown":
                source_type_counter.update(_memory_values([item.source_type]))
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
            "material_source_type_signals": _counter_items(material_source_type_counter, limit=6),
            "pdf_year_signals": _counter_items(year_counter, limit=6),
            "pdf_question_type_signals": _counter_items(question_type_counter, limit=6),
            "pdf_chapter_signals": _counter_items(chapter_counter, limit=8),
            "pdf_solution_signals": _counter_items(solution_counter, limit=8),
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
        query: str,
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
        current_query_memory = _current_query_memory_payload(query)
        payload: dict[str, Any] = {
            "profile": profile,
            "current_query_memory": current_query_memory,
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
            matched.append({"material_id": int(material.id), "title": _clean_memory_text(material.title, max_chars=120), "matched_fields": fields})
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
                interactions.append({"material_id": int(material.id), "title": _clean_memory_text(material.title, max_chars=120), "signals": flags})
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
        "title": _clean_memory_text(material.title, max_chars=120),
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
            "title": _clean_memory_text(material.title, max_chars=120),
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
        "school": _clean_memory_text(getattr(user, "school", None)),
        "college": _clean_memory_text(getattr(user, "college", None)),
        "major": _clean_memory_text(getattr(user, "major", None)),
        "grade_stages": _clean_memory_text(getattr(user, "grade_stages", None)),
    }
    return {key: value for key, value in payload.items() if value}


def _evidence_page_payload(item: MaterialPageEvidence) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "material_id": item.material_id,
        "title": _clean_memory_text(item.title, max_chars=120),
        "page": item.page,
    }
    if item.question_numbers:
        payload["question_numbers"] = _memory_values(item.question_numbers)
    if item.score_points:
        payload["score_points"] = list(item.score_points)
    if item.difficulty_signals:
        payload["difficulty_signals"] = _memory_values(item.difficulty_signals)
    if item.visual_signals:
        payload["visual_signals"] = _memory_values(item.visual_signals)
    if item.chapter_signals:
        payload["chapter_signals"] = _memory_values(item.chapter_signals)
    if item.solution_signals:
        payload["solution_signals"] = _memory_values(item.solution_signals)
    if item.anchor_terms:
        payload["anchor_terms"] = _memory_values(item.anchor_terms)
    if item.anchor_text:
        payload["anchor_text"] = _clean_memory_text(item.anchor_text, max_chars=240)
    if item.source_type != "unknown":
        payload["source_type"] = _clean_memory_text(item.source_type)
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
    return [cleaned for item in parsed if (cleaned := _clean_memory_text(item))]


def _material_text(material: MaterialRecord) -> str:
    return " ".join(
        value
        for value in [
            _clean_memory_text(material.title),
            _clean_memory_text(material.description),
            _clean_memory_text(material.keywords),
            " ".join(_json_string_list(material.tags_json)),
        ]
        if value
    )


def _signal_terms(text: str) -> list[str]:
    normalized = text.lower()
    return [term for term in MEMORY_SIGNAL_TERMS if term.lower() in normalized]


def _material_course_terms(text: str) -> list[str]:
    normalized = text.lower()
    return [label for label, aliases in MATERIAL_COURSE_PATTERNS if any(alias.lower() in normalized for alias in aliases)]


def _material_source_type_terms(text: str) -> list[str]:
    normalized = text.lower()
    return [label for label, aliases in MATERIAL_SOURCE_TYPE_PATTERNS if any(alias.lower() in normalized for alias in aliases)]


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


def _current_query_memory_payload(query: str) -> dict[str, Any]:
    normalized = query.strip().lower()
    constraints = _query_study_constraints(normalized)
    problem_context = _query_problem_context(normalized)
    preferences = _query_learning_preferences(normalized)
    if not constraints and not problem_context and not preferences:
        return {}
    payload: dict[str, Any] = {
        "study_constraints": constraints,
        "problem_context": problem_context,
        "learning_preferences": preferences,
        "scope": "current_request_only",
        "persistence": "not_persisted",
    }
    return {key: value for key, value in payload.items() if value not in (None, [], {}, "")}


def _query_study_constraints(normalized_query: str) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    horizon = _query_study_horizon(normalized_query)
    if horizon:
        payload.update(horizon)
    target_score = _query_target_score(normalized_query)
    if target_score is not None:
        payload["target_score"] = target_score
    daily_hours = _query_daily_hours(normalized_query)
    if daily_hours is not None:
        payload["daily_available_hours"] = daily_hours
    weak_points = _query_weak_points(normalized_query)
    if weak_points:
        payload["weak_points"] = weak_points
    return payload


def _query_study_horizon(normalized_query: str) -> dict[str, Any]:
    for phrase, days in QUERY_STUDY_TIME_PHRASES:
        if phrase in normalized_query:
            return {"time_horizon": phrase, "days_until_exam": days}
    day_match = re.search(r"(?<!\d)(\d{1,3})\s*(?:天|日)\s*后", normalized_query)
    if day_match:
        days = max(0, min(180, int(day_match.group(1))))
        return {"time_horizon": f"{days}天后", "days_until_exam": days}
    week_match = re.search(r"(?<!\d)(\d{1,2})\s*(?:周|星期)\s*后", normalized_query)
    if week_match:
        weeks = max(0, min(26, int(week_match.group(1))))
        return {"time_horizon": f"{weeks}周后", "days_until_exam": weeks * 7}
    month_match = re.search(r"(?<!\d)(\d{1,2})\s*个?月\s*后", normalized_query)
    if month_match:
        months = max(0, min(6, int(month_match.group(1))))
        return {"time_horizon": f"{months}个月后", "days_until_exam": months * 30}
    return {}


def _query_target_score(normalized_query: str) -> int | None:
    for pattern in (
        r"(?:目标|考到|想考|希望|争取).{0,8}?(\d{2,3})\s*分?",
        r"(\d{2,3})\s*分",
    ):
        match = re.search(pattern, normalized_query)
        if not match:
            continue
        score = int(match.group(1))
        if 1 <= score <= 100:
            return score
    return None


def _query_daily_hours(normalized_query: str) -> float | None:
    match = re.search(r"(?:每天|每日|一天).{0,8}?(\d{1,2}(?:\.\d)?)\s*(?:小时|h)", normalized_query)
    if not match:
        return None
    hours = float(match.group(1))
    if 0 < hours <= 16:
        return hours
    return None


def _query_weak_points(normalized_query: str) -> list[str]:
    if not any(marker in normalized_query for marker in ("薄弱", "不会", "不懂", "不熟", "不太会", "卡住", "看不懂")):
        return []
    return [term for term in QUERY_WEAKNESS_TERMS if term.lower() in normalized_query][:6]


def _query_problem_context(normalized_query: str) -> dict[str, Any]:
    focus_areas = []
    for label, aliases in QUERY_PROBLEM_FOCUS_PATTERNS:
        if any(alias.lower() in normalized_query for alias in aliases) and label not in focus_areas:
            focus_areas.append(label)
    question_numbers = _query_question_numbers(normalized_query)
    knowledge_points = [term for term in QUERY_WEAKNESS_TERMS if term.lower() in normalized_query][:6]
    payload: dict[str, Any] = {
        "focus_areas": focus_areas[:4],
        "question_numbers": question_numbers,
        "knowledge_points": knowledge_points,
    }
    return {key: value for key, value in payload.items() if value}


def _query_question_numbers(normalized_query: str) -> list[str]:
    patterns = (
        r"第\s*([0-9一二三四五六七八九十]{1,3})\s*[题問问]",
        r"\b[Qq]\s*([0-9]{1,2})\b",
        r"[Qq]uestion\s*([0-9]{1,2})",
    )
    result: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, normalized_query):
            label = f"第{str(match).strip()}题"
            if label not in result:
                result.append(label)
            if len(result) >= 6:
                return result
    return result


def _query_learning_preferences(normalized_query: str) -> list[str]:
    result: list[str] = []
    for label, aliases in QUERY_LEARNING_PREFERENCE_PATTERNS:
        if any(alias.lower() in normalized_query for alias in aliases) and label not in result:
            result.append(label)
    return result[:6]


def _compact_query_focus(query: str) -> list[str]:
    terms = [_clean_memory_text(item) for item in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", _redact_memory_sensitive_text(query))]
    result: list[str] = []
    for term in terms:
        if term.startswith("redacted"):
            continue
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


def _clean_memory_text(value: Any, *, max_chars: int = 80) -> str:
    if value is None:
        return ""
    normalized = re.sub(r"\s+", " ", str(value)).strip()
    return _redact_memory_sensitive_text(normalized)[:max_chars]


def _memory_values(values: Any, *, limit: int = 8, max_chars: int = 80) -> list[str]:
    result: list[str] = []
    iterable = (values,) if isinstance(values, (str, int, float)) else values or ()
    for value in iterable:
        cleaned = _clean_memory_text(value, max_chars=max_chars)
        if cleaned and cleaned not in result:
            result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def _redact_memory_sensitive_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(
        r"https?://[^\s,;，；。]+|www\.[^\s,;，；。]+",
        "[redacted-url]",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[redacted-email]", text)
    text = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[redacted-phone]", text)
    text = re.sub(
        r"(?i)(api[_-]?key|token|secret|authorization|bearer)\s*[:=]\s*[^\s,;，；。]+",
        "[redacted-secret]",
        text,
    )
    text = re.sub(
        r"(?i)(?<![A-Za-z0-9_-])(?:sk|tp)-[A-Za-z0-9_-]{16,}(?![A-Za-z0-9_-])",
        "[redacted-secret]",
        text,
    )
    text = _redact_memory_identity_numbers(text)
    text = _redact_memory_labeled_ids(text)
    text = _redact_memory_messenger_handles(text)
    return re.sub(r"(?<!\d)\d{12,24}(?!\d)", "[redacted-number]", text)


def _redact_memory_identity_numbers(text: str) -> str:
    return re.sub(
        r"(?<![A-Za-z0-9])\d{6}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?![A-Za-z0-9])",
        "[redacted-id-card]",
        text,
    )


def _redact_memory_labeled_ids(text: str) -> str:
    pattern = re.compile(
        r"(?i)(学号|工号|student[_ -]?id|employee[_ -]?id)\s*[:：=]?\s*[A-Za-z0-9_-]{5,24}"
    )
    return pattern.sub(lambda match: f"{match.group(1)}=[redacted-id]", text)


def _redact_memory_messenger_handles(text: str) -> str:
    latin_pattern = re.compile(
        r"(?i)(?<![A-Za-z0-9_])(qq|wechat|weixin|wx|vx)(?![A-Za-z0-9_])\s*[:：=]?\s*[A-Za-z0-9_-]{5,32}"
    )
    text = latin_pattern.sub(lambda match: f"{match.group(1)}=[redacted-contact]", text)
    chinese_pattern = re.compile(r"(微信|微信号|微 信)\s*[:：=]?\s*[A-Za-z0-9_-]{5,32}")
    return chinese_pattern.sub(lambda match: f"{match.group(1)}=[redacted-contact]", text)
