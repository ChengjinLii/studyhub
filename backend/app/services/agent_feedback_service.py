from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.observability import get_runtime_metrics
from app.models.materials import MaterialRecord
from app.repos.material_repo import MaterialRepository
from app.schemas.ai import AiFeedbackPayload


ALLOWED_FEEDBACK_HOOKS = {
    "useful",
    "not_useful",
    "too_easy",
    "too_hard",
    "not_relevant",
}

USER_MEMORY_FEEDBACK_SUMMARIES = {
    "useful": "用户认为这次推荐或学习建议有帮助。",
    "not_useful": "用户认为这次推荐或学习建议帮助不大。",
    "too_easy": "用户认为这次学习建议偏简单。",
    "too_hard": "用户认为这次学习建议偏困难。",
    "not_relevant": "用户认为这次推荐与需求不够相关。",
}


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
        accepted_material_ids = self._visible_material_ids(session, payload.selectedMaterialIds)
        redacted_note = _redact_note(payload.note)
        if hook not in ALLOWED_FEEDBACK_HOOKS:
            result = {
                "accepted": False,
                "reason": "invalid_hook",
                "allowedHooks": sorted(ALLOWED_FEEDBACK_HOOKS),
                "selectedMaterialIds": accepted_material_ids,
                "redactedNote": redacted_note,
                "memoryCandidates": [],
                "persistence": "not_persisted",
                "privacyBoundary": _privacy_boundary(),
            }
            self._record_feedback_metric(hook=hook or "unknown", status="rejected", personal_memory_enabled=personal_memory_enabled, selected=bool(accepted_material_ids))
            return result

        candidates = self._memory_candidates(
            hook=hook,
            redacted_note=redacted_note,
            selected_material_ids=accepted_material_ids,
            personal_memory_enabled=personal_memory_enabled,
        )
        result = {
            "accepted": True,
            "hook": hook,
            "selectedMaterialIds": accepted_material_ids,
            "redactedNote": redacted_note,
            "personalMemoryEnabled": personal_memory_enabled,
            "memoryCandidates": candidates,
            "persistence": "not_persisted",
            "privacyBoundary": _privacy_boundary(),
        }
        self._record_feedback_metric(hook=hook, status="accepted", personal_memory_enabled=personal_memory_enabled, selected=bool(accepted_material_ids))
        return result

    def _visible_material_ids(self, session: Session, selected_material_ids: list[int]) -> list[int]:
        accepted: list[int] = []
        for material_id in selected_material_ids:
            material = self.material_repo.get_material(session, int(material_id))
            if material is None or not _is_visible_material(material):
                continue
            accepted.append(int(material.id))
        return accepted

    def _memory_candidates(
        self,
        *,
        hook: str,
        redacted_note: str,
        selected_material_ids: list[int],
        personal_memory_enabled: bool,
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        if personal_memory_enabled:
            value = USER_MEMORY_FEEDBACK_SUMMARIES[hook]
            if redacted_note:
                value = f"{value} 用户补充：{redacted_note}"
            candidates.append(
                {
                    "scope": "user",
                    "key": "agent_feedback_preference",
                    "value": value[:240],
                    "source": "agent_feedback",
                    "confidence": _feedback_confidence(hook),
                    "materialIds": selected_material_ids,
                }
            )
        if selected_material_ids:
            candidates.append(
                {
                    "scope": "platform",
                    "key": "recommendation_feedback_signal",
                    "value": hook,
                    "source": "agent_feedback_aggregate",
                    "confidence": 0.5,
                    "materialIds": selected_material_ids,
                    "privacy": "anonymous_aggregate_candidate",
                }
            )
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
    text = re.sub(r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*\S+", r"\1=[redacted-secret]", text)
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


def _feedback_confidence(hook: str) -> float:
    if hook == "useful":
        return 0.75
    if hook in {"too_easy", "too_hard"}:
        return 0.68
    return 0.6


def _privacy_boundary() -> str:
    return (
        "Feedback is converted into bounded memory candidates only. User-scope candidates must stay private to the "
        "current user, while platform-scope candidates are anonymous aggregates and contain no raw personal contact data."
    )
