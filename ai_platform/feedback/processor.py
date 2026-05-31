from __future__ import annotations

from dataclasses import dataclass

from ai_platform.agents.genrec_agent import GenRecResponse
from ai_platform.memory.schemas import MemoryCandidate
from ai_platform.memory.store import JsonHermesMemoryStore, StoredMemory
from ai_platform.preprocessing.ai_document import redact_contacts


ALLOWED_FEEDBACK_HOOKS = {"useful", "not_useful", "too_easy", "too_hard", "not_relevant"}


@dataclass(frozen=True)
class FeedbackEvent:
    hook: str
    note: str = ""
    selected_item_ids: tuple[str, ...] = ()

    def sanitized_note(self) -> str:
        return redact_contacts(self.note)[:160]


class FeedbackProcessor:
    """Turns safe feedback into memory candidates and stores them in JSON."""

    def __init__(self, memory_store: JsonHermesMemoryStore) -> None:
        self.memory_store = memory_store

    def process(self, response: GenRecResponse, event: FeedbackEvent) -> list[StoredMemory]:
        if event.hook not in ALLOWED_FEEDBACK_HOOKS:
            raise ValueError(f"unsupported feedback hook: {event.hook}")
        if event.hook not in response.feedback_hooks:
            raise ValueError(f"feedback hook is not enabled for this response: {event.hook}")
        recommended_ids = {item["id"] for item in response.recommended_items}
        selected_ids = tuple(item_id for item_id in event.selected_item_ids if item_id in recommended_ids)
        candidates = [MemoryCandidate.from_dict(dict(candidate)) for candidate in response.memory_candidates]
        candidates.extend(_feedback_candidates(event, selected_ids))
        return self.memory_store.upsert_candidates(candidates)


def _feedback_candidates(event: FeedbackEvent, selected_ids: tuple[str, ...]) -> list[MemoryCandidate]:
    candidates = [
        MemoryCandidate(
            scope="user",
            key="last_feedback_hook",
            value=event.hook,
            confidence=0.6,
            source="feedback",
        )
    ]
    note = event.sanitized_note()
    if note:
        candidates.append(
            MemoryCandidate(
                scope="user",
                key="last_feedback_summary",
                value=note,
                confidence=0.55,
                source="feedback",
            )
        )
    if selected_ids:
        candidates.append(
            MemoryCandidate(
                scope="platform",
                key="positive_or_negative_feedback_items",
                value=", ".join(selected_ids),
                confidence=0.5,
                source=f"feedback:{event.hook}",
            )
        )
    return candidates
