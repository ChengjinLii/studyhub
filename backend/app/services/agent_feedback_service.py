from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.observability import get_runtime_metrics
from app.models.materials import MaterialRecord
from app.repos.material_repo import MaterialRepository
from app.schemas.ai import AiFeedbackPayload
from app.services.agent_material_signal_service import build_material_signals, safe_material_value


ALLOWED_FEEDBACK_HOOKS = {
    "useful",
    "not_useful",
    "too_easy",
    "too_hard",
    "not_relevant",
}

FEEDBACK_MEMORY_CANDIDATE_SCHEMA = "agent-feedback-memory-candidate-v1"
FEEDBACK_CANDIDATE_LIFECYCLE_SCHEMA = "agent-feedback-candidate-lifecycle-v1"

USER_MEMORY_FEEDBACK_SUMMARIES = {
    "useful": "用户认为这次推荐或学习建议有帮助。",
    "not_useful": "用户认为这次推荐或学习建议帮助不大。",
    "too_easy": "用户认为这次学习建议偏简单。",
    "too_hard": "用户认为这次学习建议偏困难。",
    "not_relevant": "用户认为这次推荐与需求不够相关。",
}

HOOK_DERIVED_SIGNALS: dict[str, tuple[str, str]] = {
    "useful": ("positive_feedback", "有帮助"),
    "not_useful": ("content_issues", "帮助不足"),
    "too_easy": ("difficulty_feedback", "偏简单"),
    "too_hard": ("difficulty_feedback", "偏困难"),
    "not_relevant": ("content_issues", "相关性不足"),
}

FEEDBACK_NOTE_SIGNAL_PATTERNS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("learning_preferences", "补基础优先", ("基础差", "基础弱", "零基础", "看不懂", "听不懂")),
    ("learning_preferences", "考前冲刺", ("速成", "冲刺", "考前", "来不及", "短期")),
    ("learning_preferences", "刷题优先", ("刷题", "真题", "练习", "套卷", "做题")),
    ("learning_preferences", "详细解析", ("详细解析", "一步步", "讲清楚", "讲明白", "解析更细")),
    ("learning_preferences", "查漏补缺", ("查漏补缺", "错题", "薄弱", "短板")),
    ("content_issues", "相关性不足", ("不相关", "没关系", "跑题", "不是这门课")),
    ("content_issues", "证据不足", ("找不到", "没有来源", "页码不对", "引用不对", "资料不存在")),
    ("content_issues", "解析质量风险", ("解析错误", "答案不对", "讲错", "不准确")),
)

MATERIAL_COURSE_SIGNAL_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("电子系统设计", ("电子系统设计", "esd")),
    ("通信原理", ("通信原理", "cps")),
    ("信号与系统", ("信号与系统", "signals", "signal")),
    ("数据结构", ("数据结构",)),
    ("高等数学", ("高等数学", "高数", "微积分")),
    ("概率论", ("概率论",)),
)

MATERIAL_SOURCE_SIGNAL_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("往年真题", ("真题", "往年", "历年", "试卷", "期末题", "样卷", "考题")),
    ("答案解析", ("解析", "答案", "标答", "参考答案", "讲解")),
    ("讲义笔记", ("笔记", "讲义", "导图", "课件")),
    ("复习速成", ("速成", "提纲", "复习", "冲刺")),
    ("经验分享", ("经验", "经验贴", "攻略")),
)


class AgentFeedbackService:
    """Builds privacy-safe memory candidates from explicit Agent feedback.

    This service does not persist memory yet. It prepares bounded user/platform
    candidates so the write path can be connected later with a schema migration
    and user-facing deletion contract.
    """

    def __init__(self, material_repo: MaterialRepository) -> None:
        self.material_repo = material_repo

    def process_feedback(
        self,
        session: Session,
        payload: AiFeedbackPayload,
        *,
        personal_memory_enabled: bool,
    ) -> dict[str, Any]:
        hook = payload.hook.strip().lower()
        accepted_materials = self._visible_materials(session, payload.selectedMaterialIds)
        accepted_material_ids = [int(material.id) for material in accepted_materials]
        redacted_note = _redact_note(payload.note)
        if hook not in ALLOWED_FEEDBACK_HOOKS:
            result = {
                "accepted": False,
                "reason": "invalid_hook",
                "allowedHooks": sorted(ALLOWED_FEEDBACK_HOOKS),
                "selectedMaterialIds": accepted_material_ids,
                "redactedNote": redacted_note,
                "memoryCandidates": [],
                "candidateLifecycleSchema": FEEDBACK_CANDIDATE_LIFECYCLE_SCHEMA,
                "persistence": "not_persisted",
                "privacyBoundary": _privacy_boundary(),
            }
            self._record_feedback_metric(hook=hook or "unknown", status="rejected", personal_memory_enabled=personal_memory_enabled, selected=bool(accepted_material_ids))
            return result

        candidates = self._memory_candidates(
            hook=hook,
            redacted_note=redacted_note,
            selected_materials=accepted_materials,
            personal_memory_enabled=personal_memory_enabled,
        )
        result = {
            "accepted": True,
            "hook": hook,
            "selectedMaterialIds": accepted_material_ids,
            "redactedNote": redacted_note,
            "personalMemoryEnabled": personal_memory_enabled,
            "memoryCandidates": candidates,
            "candidateLifecycleSchema": FEEDBACK_CANDIDATE_LIFECYCLE_SCHEMA,
            "persistence": "not_persisted",
            "privacyBoundary": _privacy_boundary(),
        }
        self._record_feedback_metric(hook=hook, status="accepted", personal_memory_enabled=personal_memory_enabled, selected=bool(accepted_material_ids))
        return result

    def _visible_materials(self, session: Session, selected_material_ids: list[int]) -> list[MaterialRecord]:
        accepted: list[MaterialRecord] = []
        seen: set[int] = set()
        for material_id in selected_material_ids:
            material = self.material_repo.get_material(session, int(material_id))
            if material is None or not _is_visible_material(material) or int(material.id) in seen:
                continue
            seen.add(int(material.id))
            accepted.append(material)
        return accepted

    def _memory_candidates(
        self,
        *,
        hook: str,
        redacted_note: str,
        selected_materials: list[MaterialRecord],
        personal_memory_enabled: bool,
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        selected_material_ids = [int(material.id) for material in selected_materials]
        derived_signals = _feedback_derived_signals(hook, redacted_note)
        selected_material_signals = _selected_material_signals(selected_materials)
        if personal_memory_enabled:
            user_candidate: dict[str, Any] = {
                "schema": FEEDBACK_MEMORY_CANDIDATE_SCHEMA,
                "scope": "user",
                "key": "agent_feedback_preference",
                "value": _feedback_memory_summary(hook, derived_signals),
                "source": "agent_feedback",
                "writeMode": "deferred_not_persisted",
                "confidence": _feedback_confidence(hook),
                "materialIds": selected_material_ids,
                "signalBasis": _signal_basis(
                    hook=hook,
                    selected_material_ids=selected_material_ids,
                    derived_signals=derived_signals,
                    selected_material_signals=selected_material_signals,
                    scope="user",
                ),
                "privacy": "current_user_private_candidate",
                "lifecycle": _candidate_lifecycle("user"),
            }
            if derived_signals:
                user_candidate["derivedSignals"] = derived_signals
            if selected_material_signals:
                user_candidate["selectedMaterialSignals"] = selected_material_signals
            _attach_candidate_version(user_candidate)
            candidates.append(user_candidate)
        if selected_material_ids:
            platform_candidate: dict[str, Any] = {
                "schema": FEEDBACK_MEMORY_CANDIDATE_SCHEMA,
                "scope": "platform",
                "key": "recommendation_feedback_signal",
                "value": hook,
                "source": "agent_feedback_aggregate",
                "writeMode": "deferred_not_persisted",
                "confidence": 0.5,
                "materialIds": selected_material_ids,
                "privacy": "anonymous_aggregate_candidate",
                "signalBasis": _signal_basis(
                    hook=hook,
                    selected_material_ids=selected_material_ids,
                    derived_signals=derived_signals,
                    selected_material_signals=selected_material_signals,
                    scope="platform",
                ),
                "anonymization": {
                    "rawNotePersisted": False,
                    "rawUserIdentityPersisted": False,
                    "personalMemoryMixedIntoPlatform": False,
                },
                "lifecycle": _candidate_lifecycle("platform"),
            }
            if derived_signals:
                platform_candidate["aggregateSignals"] = derived_signals
            if selected_material_signals:
                platform_candidate["selectedMaterialSignals"] = selected_material_signals
            _attach_candidate_version(platform_candidate)
            candidates.append(platform_candidate)
        return candidates

    def _record_feedback_metric(
        self,
        *,
        hook: str,
        status: str,
        personal_memory_enabled: bool,
        selected: bool,
    ) -> None:
        get_runtime_metrics().record_ai_agent_feedback(
            hook=hook,
            status=status,
            personal_memory=personal_memory_enabled,
            selected_materials=selected,
        )


def _is_visible_material(material: MaterialRecord) -> bool:
    return material.deleted_at is None and material.status not in {"REMOVED", "HIDDEN"}


def _redact_note(value: str | None) -> str:
    if not value:
        return ""
    text = " ".join(str(value).split())[:500]
    text = re.sub(r"https?://\S+|www\.\S+", "[redacted-url]", text, flags=re.IGNORECASE)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[redacted-email]", text)
    text = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[redacted-phone]", text)
    text = re.sub(r"(?i)(?<![A-Za-z0-9_-])authorization\s*[:=]?\s*bearer\s+\S+", "[redacted-secret]", text)
    text = re.sub(r"(?i)(?<![A-Za-z0-9_-])bearer\s+\S+", "[redacted-secret]", text)
    text = re.sub(
        r"(?i)(?<![A-Za-z0-9_-])(?:sk|tp)-[A-Za-z0-9_-]{16,}(?![A-Za-z0-9_-])",
        "[redacted-secret]",
        text,
    )
    text = re.sub(
        r"(?i)(?<![A-Za-z0-9_-])(?:api[_-]?key|token|secret|authorization)(?![A-Za-z0-9_-])\s*[:=]\s*\S+",
        "[redacted-secret]",
        text,
    )
    text = _redact_identity_numbers(text)
    text = _redact_labeled_ids(text)
    text = _redact_messenger_handles(text)
    text = re.sub(r"(?<!\d)\d{12,24}(?!\d)", "[redacted-number]", text)
    return text[:240]


def _redact_identity_numbers(text: str) -> str:
    return re.sub(
        r"(?<![A-Za-z0-9])\d{6}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?![A-Za-z0-9])",
        "[redacted-id-card]",
        text,
    )


def _redact_labeled_ids(text: str) -> str:
    pattern = re.compile(
        r"(?i)(学号|工号|student[_ -]?id|employee[_ -]?id)\s*[:：=]?\s*[A-Za-z0-9_-]{5,24}"
    )
    return pattern.sub(lambda match: f"{match.group(1)}=[redacted-id]", text)


def _redact_messenger_handles(text: str) -> str:
    latin_pattern = re.compile(
        r"(?i)(?<![A-Za-z0-9_])(qq|wechat|weixin|wx|vx)(?![A-Za-z0-9_])\s*[:：=]?\s*[A-Za-z0-9_-]{5,32}"
    )
    text = latin_pattern.sub(lambda match: f"{match.group(1)}=[redacted-contact]", text)
    chinese_pattern = re.compile(r"(微信|微信号|微 信)\s*[:：=]?\s*[A-Za-z0-9_-]{5,32}")
    return chinese_pattern.sub(lambda match: f"{match.group(1)}=[redacted-contact]", text)


def _feedback_derived_signals(hook: str, redacted_note: str) -> dict[str, list[str]]:
    signals: dict[str, list[str]] = {}
    hook_signal = HOOK_DERIVED_SIGNALS.get(hook)
    if hook_signal:
        _append_signal(signals, hook_signal[0], hook_signal[1])
    normalized_note = redacted_note.lower()
    if normalized_note:
        for category, label, aliases in FEEDBACK_NOTE_SIGNAL_PATTERNS:
            if any(alias.lower() in normalized_note for alias in aliases):
                _append_signal(signals, category, label)
    return {key: values[:6] for key, values in signals.items() if values}


def _feedback_memory_summary(hook: str, derived_signals: dict[str, list[str]]) -> str:
    summary = USER_MEMORY_FEEDBACK_SUMMARIES[hook]
    labels = [label for values in derived_signals.values() for label in values]
    if labels:
        summary = f"{summary} 反馈信号：{'、'.join(labels[:8])}。"
    return summary[:240]


def _selected_material_signals(materials: list[MaterialRecord]) -> dict[str, list[str]]:
    signals: dict[str, list[str]] = {}
    for material in materials[:10]:
        text = _material_feedback_text(material)
        normalized_text = text.lower()
        for label, aliases in MATERIAL_COURSE_SIGNAL_PATTERNS:
            if any(alias.lower() in normalized_text for alias in aliases):
                _append_signal(signals, "courses", label)
        for label, aliases in MATERIAL_SOURCE_SIGNAL_PATTERNS:
            if any(alias.lower() in normalized_text for alias in aliases):
                _append_signal(signals, "sourceTypes", label)
        material_signals = build_material_signals(material)
        for label in material_signals.quality_signals[:4]:
            _append_signal(signals, "qualitySignals", label)
        for label in material_signals.risk_signals[:4]:
            _append_signal(signals, "riskSignals", label)
    return {key: values[:8] for key, values in signals.items() if values}


def _material_feedback_text(material: MaterialRecord) -> str:
    values = [
        safe_material_value(material, "title"),
        safe_material_value(material, "description"),
        safe_material_value(material, "keywords"),
        safe_material_value(material, "school"),
        safe_material_value(material, "college"),
        safe_material_value(material, "major"),
        *_material_tags(material),
    ]
    return " ".join(_clean_signal_text(value) for value in values if value)


def _material_tags(material: MaterialRecord) -> list[str]:
    raw = safe_material_value(material, "tags_json")
    if not raw:
        return []
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [_clean_signal_text(item) for item in parsed if _clean_signal_text(item)]


def _clean_signal_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()[:80]


def _append_signal(signals: dict[str, list[str]], category: str, label: str) -> None:
    values = signals.setdefault(category, [])
    if label not in values:
        values.append(label)


def _feedback_confidence(hook: str) -> float:
    if hook == "useful":
        return 0.75
    if hook in {"too_easy", "too_hard"}:
        return 0.68
    return 0.6


def _signal_basis(
    *,
    hook: str,
    selected_material_ids: list[int],
    derived_signals: dict[str, list[str]],
    selected_material_signals: dict[str, list[str]],
    scope: str,
) -> dict[str, Any]:
    return {
        "schema": FEEDBACK_MEMORY_CANDIDATE_SCHEMA,
        "scope": scope,
        "hook": hook,
        "selectedMaterialCount": len(selected_material_ids),
        "selectedMaterialIds": selected_material_ids[:10],
        "derivedSignalKeys": sorted(derived_signals),
        "selectedMaterialSignalKeys": sorted(selected_material_signals),
        "rawNoteIncluded": False,
        "persistence": "not_persisted",
    }


def _candidate_lifecycle(scope: str) -> dict[str, Any]:
    if scope == "user":
        return {
            "schema": FEEDBACK_CANDIDATE_LIFECYCLE_SCHEMA,
            "persistence": "not_persisted",
            "writeMode": "deferred_not_persisted",
            "requiresExplicitFutureWritePath": True,
            "deleteWithPersonalMemory": True,
            "platformEligible": False,
            "rawNotePersisted": False,
        }
    return {
        "schema": FEEDBACK_CANDIDATE_LIFECYCLE_SCHEMA,
        "persistence": "not_persisted",
        "writeMode": "deferred_not_persisted",
        "requiresAnonymousAggregation": True,
        "deleteWithPersonalMemory": False,
        "rawNotePersisted": False,
        "rawUserIdentityPersisted": False,
    }


def _attach_candidate_version(candidate: dict[str, Any]) -> None:
    basis = {
        "schema": candidate.get("schema"),
        "scope": candidate.get("scope"),
        "key": candidate.get("key"),
        "value": candidate.get("value"),
        "materialIds": candidate.get("materialIds") or [],
        "derivedSignals": candidate.get("derivedSignals") or candidate.get("aggregateSignals") or {},
        "selectedMaterialSignals": candidate.get("selectedMaterialSignals") or {},
        "signalBasis": candidate.get("signalBasis") or {},
        "lifecycle": candidate.get("lifecycle") or {},
    }
    fingerprint = _stable_feedback_fingerprint(basis)
    candidate["versionFingerprint"] = fingerprint
    candidate["version"] = f"feedback-candidate-v1-{fingerprint[:12]}"


def _stable_feedback_fingerprint(value: dict[str, Any]) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


def _privacy_boundary() -> str:
    return (
        "Feedback is converted into bounded memory candidates only. User-scope candidates must stay private to the "
        "current user, while platform-scope candidates are anonymous aggregates and contain no raw personal contact data."
    )
