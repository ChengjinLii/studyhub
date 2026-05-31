from __future__ import annotations

from ai_platform.memory.schemas import MemoryCandidate
from ai_platform.router.schemas import QueryUnderstanding


class MockHermesMemoryExtractor:
    """Extracts safe memory candidates without writing any production user state."""

    def extract_user_candidates(self, understanding: QueryUnderstanding, feedback: str | None = None) -> list[MemoryCandidate]:
        candidates: list[MemoryCandidate] = []
        entities = understanding.entities
        if entities.course:
            candidates.append(
                MemoryCandidate(
                    scope="user",
                    key="active_course",
                    value=entities.course,
                    confidence=0.82,
                    source="query_understanding",
                )
            )
        if entities.level:
            candidates.append(
                MemoryCandidate(
                    scope="user",
                    key="learning_level",
                    value=entities.level,
                    confidence=0.72,
                    source="query_understanding",
                )
            )
        for material_type in entities.material_types:
            candidates.append(
                MemoryCandidate(
                    scope="user",
                    key="preferred_material_type",
                    value=material_type,
                    confidence=0.68,
                    source="query_understanding",
                )
            )
        if feedback:
            candidates.append(
                MemoryCandidate(
                    scope="user",
                    key="last_feedback_summary",
                    value=feedback[:80],
                    confidence=0.55,
                    source="feedback",
                )
            )
        return candidates

    def summarize_platform_candidates(self, recommended_item_ids: list[str]) -> list[MemoryCandidate]:
        if not recommended_item_ids:
            return []
        return [
            MemoryCandidate(
                scope="platform",
                key="effective_recommendation_bundle",
                value=", ".join(recommended_item_ids[:5]),
                confidence=0.5,
                source="studycopilot_demo",
            )
        ]
