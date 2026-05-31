from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ai_platform.feedback.processor import FeedbackEvent
from ai_platform.memory.schemas import MemoryCandidate
from ai_platform.serving.llm_provider import ChatCompletionRequest, ChatMessage, ChatProvider
from ai_platform.shared.privacy import sanitize_for_model
from ai_platform.shared.prompt_guard import PromptInjectionGuard


ALLOWED_SCOPES = {"user", "platform"}
ALLOWED_KEYS = {
    "active_course",
    "learning_level",
    "preferred_material_type",
    "feedback_summary",
    "effective_recommendation_bundle",
    "avoid_recommendation_pattern",
    "platform_review_tip",
}


@dataclass(frozen=True)
class MemorySummaryResult:
    candidates: list[MemoryCandidate]
    fallback_used: bool = False
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "fallbackUsed": self.fallback_used,
            "warnings": list(self.warnings),
        }


class MockMemorySummarizer:
    """Summarizes safe feedback into memory candidates without production writes."""

    def summarize_feedback(self, events: list[FeedbackEvent], *, recommended_item_ids: list[str]) -> MemorySummaryResult:
        candidates: list[MemoryCandidate] = []
        hooks = [event.hook for event in events]
        if hooks:
            candidates.append(
                MemoryCandidate(
                    scope="user",
                    key="feedback_summary",
                    value=", ".join(hooks[-5:]),
                    confidence=0.55,
                    source="feedback_summary",
                )
            )
        notes = [event.sanitized_note() for event in events if event.sanitized_note()]
        if notes:
            candidates.append(
                MemoryCandidate(
                    scope="user",
                    key="feedback_summary",
                    value="；".join(notes[-3:])[:160],
                    confidence=0.58,
                    source="feedback_summary",
                )
            )
        if recommended_item_ids:
            candidates.append(
                MemoryCandidate(
                    scope="platform",
                    key="effective_recommendation_bundle",
                    value=", ".join(recommended_item_ids[:5]),
                    confidence=0.5,
                    source="feedback_summary",
                )
            )
        return MemorySummaryResult(candidates=candidates)


class LLMMemorySummarizer:
    """LLM-backed Hermes summarizer with schema and key allow-list validation."""

    def __init__(self, chat_provider: ChatProvider, *, fallback: MockMemorySummarizer | None = None) -> None:
        self.chat_provider = chat_provider
        self.fallback = fallback or MockMemorySummarizer()

    def summarize_feedback(self, events: list[FeedbackEvent], *, recommended_item_ids: list[str]) -> MemorySummaryResult:
        fallback_result = self.fallback.summarize_feedback(events, recommended_item_ids=recommended_item_ids)
        guard_text = " ".join(event.note for event in events)
        guard_result = PromptInjectionGuard().inspect(guard_text)
        if guard_result.risky:
            return MemorySummaryResult(
                candidates=fallback_result.candidates,
                fallback_used=True,
                warnings=tuple(dict.fromkeys((*fallback_result.warnings, *guard_result.warnings(), "llm_memory_fallback:prompt_injection_guard"))),
            )
        try:
            response = self.chat_provider.complete(
                ChatCompletionRequest(
                    messages=[
                        ChatMessage(
                            role="system",
                            content=(
                                "You are StudyHub Hermes Memory Summarizer. Return strict JSON only. "
                                "Extract safe memory candidates from feedback. Use only allowed scopes and keys. "
                                "Do not include contacts, payment data, secrets, URLs, or raw private text."
                            ),
                        ),
                        ChatMessage(role="user", content=_memory_prompt(events, recommended_item_ids)),
                    ],
                    temperature=0.0,
                    max_tokens=900,
                    response_format={"type": "json_object"},
                )
            )
            return MemorySummaryResult(candidates=parse_memory_candidates_json(response.content, fallback=fallback_result.candidates))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
            return MemorySummaryResult(
                candidates=fallback_result.candidates,
                fallback_used=True,
                warnings=(*fallback_result.warnings, f"llm_memory_fallback:{exc.__class__.__name__}"),
            )


def parse_memory_candidates_json(content: str, *, fallback: list[MemoryCandidate]) -> list[MemoryCandidate]:
    data = _load_json_object(content)
    raw_candidates = data.get("candidates")
    if not isinstance(raw_candidates, list):
        raise ValueError("candidates must be a list")
    candidates: list[MemoryCandidate] = []
    for item in raw_candidates[:8]:
        if not isinstance(item, dict):
            continue
        scope = _clean_text(item.get("scope"))
        key = _clean_text(item.get("key"))
        value = _clean_text(item.get("value"))[:160]
        if scope not in ALLOWED_SCOPES or key not in ALLOWED_KEYS or not value or _contains_disallowed_text(value):
            continue
        candidates.append(
            MemoryCandidate(
                scope=scope,
                key=key,
                value=value,
                confidence=_confidence(item.get("confidence")),
                source="llm_feedback_summary",
            )
        )
    if not candidates:
        raise ValueError("no valid memory candidates")
    return candidates or fallback


def _memory_prompt(events: list[FeedbackEvent], recommended_item_ids: list[str]) -> str:
    payload = {
        "events": [
            {"hook": event.hook, "note": event.sanitized_note(), "selectedItemIds": list(event.selected_item_ids)}
            for event in events[:10]
        ],
        "recommendedItemIds": recommended_item_ids[:10],
        "allowedScopes": sorted(ALLOWED_SCOPES),
        "allowedKeys": sorted(ALLOWED_KEYS),
        "requiredOutput": {
            "candidates": [{"scope": "user|platform", "key": "allowed key only", "value": "short safe summary", "confidence": 0.0}],
        },
    }
    return json.dumps(sanitize_for_model(payload), ensure_ascii=False)


def _confidence(value: object) -> float:
    try:
        return min(max(float(value), 0.0), 1.0)
    except (TypeError, ValueError):
        return 0.5


def _contains_disallowed_text(value: str) -> bool:
    return bool(re.search(r"api\s*key|token|密码|口令|qq|微信|手机号|电话|http://|https://", value, flags=re.IGNORECASE))


def _load_json_object(content: str) -> dict[str, Any]:
    stripped = (content or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    data = json.loads(stripped)
    if not isinstance(data, dict):
        raise ValueError("memory summary must be a JSON object")
    return data


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()
