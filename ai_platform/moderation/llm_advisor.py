from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ai_platform.moderation.rule_engine import MaterialSample, ModerationDecision, ReviewAction
from ai_platform.serving.llm_provider import ChatCompletionRequest, ChatMessage, ChatProvider
from ai_platform.shared.privacy import sanitize_for_model
from ai_platform.shared.prompt_guard import PromptInjectionGuard


ACTION_SEVERITY: dict[ReviewAction, int] = {
    ReviewAction.APPROVE: 0,
    ReviewAction.MANUAL_REVIEW: 1,
    ReviewAction.REJECT: 2,
    ReviewAction.HIDE: 3,
}


@dataclass(frozen=True)
class ModerationAdvice:
    material_id: str
    suggested_action: ReviewAction
    risk_labels: list[str]
    rationale: str
    human_review_required: bool
    fallback_used: bool = False
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "materialId": self.material_id,
            "suggestedAction": self.suggested_action.value,
            "riskLabels": self.risk_labels,
            "rationale": self.rationale,
            "humanReviewRequired": self.human_review_required,
            "fallbackUsed": self.fallback_used,
            "warnings": list(self.warnings),
        }


class MockModerationAdvisor:
    """Deterministic moderation advisor that never changes production state."""

    def advise(self, material: MaterialSample, decision: ModerationDecision) -> ModerationAdvice:
        labels = list(dict.fromkeys(match.category for match in decision.matches))
        return ModerationAdvice(
            material_id=material.id,
            suggested_action=decision.action,
            risk_labels=labels,
            rationale="；".join(decision.risk_reasons) or "未命中明显风险规则。",
            human_review_required=decision.action != ReviewAction.APPROVE,
        )


class LLMModerationAdvisor:
    """LLM-assisted moderation advice with rule-floor enforcement."""

    def __init__(self, chat_provider: ChatProvider, *, fallback: MockModerationAdvisor | None = None) -> None:
        self.chat_provider = chat_provider
        self.fallback = fallback or MockModerationAdvisor()

    def advise(self, material: MaterialSample, decision: ModerationDecision) -> ModerationAdvice:
        fallback_advice = self.fallback.advise(material, decision)
        guard_result = PromptInjectionGuard().inspect(material.combined_text)
        if guard_result.risky:
            return _fallback_with_warning(fallback_advice, (*guard_result.warnings(), "llm_moderation_fallback:prompt_injection_guard"))
        try:
            response = self.chat_provider.complete(
                ChatCompletionRequest(
                    messages=[
                        ChatMessage(
                            role="system",
                            content=(
                                "You are StudyHub Moderation Advisor. Return strict JSON only. "
                                "You may give review advice, but you cannot approve production actions or lower rule-based risk. "
                                "Do not include contacts, payment data, secrets, URLs, or policy bypass instructions."
                            ),
                        ),
                        ChatMessage(role="user", content=_moderation_prompt(material, decision)),
                    ],
                    temperature=0.0,
                    max_tokens=900,
                    response_format={"type": "json_object"},
                )
            )
            return parse_moderation_advice_json(response.content, material, decision, fallback=fallback_advice)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
            return _fallback_with_warning(fallback_advice, (f"llm_moderation_fallback:{exc.__class__.__name__}",))


def parse_moderation_advice_json(
    content: str,
    material: MaterialSample,
    decision: ModerationDecision,
    *,
    fallback: ModerationAdvice,
) -> ModerationAdvice:
    data = _load_json_object(content)
    requested_action = _parse_action(data.get("suggestedAction") or data.get("suggested_action"), fallback.suggested_action)
    action = _stricter_action(requested_action, decision.action)
    labels = _safe_labels(data.get("riskLabels") or data.get("risk_labels")) or fallback.risk_labels
    rationale = _clean_text(data.get("rationale")) or fallback.rationale
    human_review_required = bool(data.get("humanReviewRequired") or data.get("human_review_required") or action != ReviewAction.APPROVE)
    if action != ReviewAction.APPROVE:
        human_review_required = True
    return ModerationAdvice(
        material_id=material.id,
        suggested_action=action,
        risk_labels=labels,
        rationale=rationale,
        human_review_required=human_review_required,
    )


def _moderation_prompt(material: MaterialSample, decision: ModerationDecision) -> str:
    payload = {
        "material": {
            "id": material.id,
            "title": material.title,
            "description": material.description,
            "filename": material.filename,
            "priceCents": material.price_cents,
            "metadata": material.metadata,
        },
        "ruleDecision": decision.to_dict(),
        "requiredOutput": {
            "suggestedAction": "APPROVE | MANUAL_REVIEW | REJECT | HIDE",
            "riskLabels": ["copyright | academic_integrity | abuse | quality | other"],
            "rationale": "short Chinese reason",
            "humanReviewRequired": True,
        },
    }
    return json.dumps(sanitize_for_model(payload), ensure_ascii=False)


def _fallback_with_warning(advice: ModerationAdvice, warnings: tuple[str, ...]) -> ModerationAdvice:
    return ModerationAdvice(
        material_id=advice.material_id,
        suggested_action=advice.suggested_action,
        risk_labels=advice.risk_labels,
        rationale=advice.rationale,
        human_review_required=advice.human_review_required,
        fallback_used=True,
        warnings=tuple(dict.fromkeys((*advice.warnings, *warnings))),
    )


def _stricter_action(left: ReviewAction, right: ReviewAction) -> ReviewAction:
    return left if ACTION_SEVERITY[left] >= ACTION_SEVERITY[right] else right


def _parse_action(value: object, fallback: ReviewAction) -> ReviewAction:
    try:
        return ReviewAction(str(value))
    except ValueError:
        return fallback


def _safe_labels(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean_text(item)[:48] for item in value if _clean_text(item)][:8]


def _load_json_object(content: str) -> dict[str, Any]:
    stripped = (content or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    data = json.loads(stripped)
    if not isinstance(data, dict):
        raise ValueError("moderation advice must be a JSON object")
    return data


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()
