from __future__ import annotations

from typing import Any


def score_task_success(final_answer: str, verifier: dict[str, Any]) -> tuple[float, list[str]]:
    normalized = final_answer.casefold()
    expected = [str(item).casefold() for item in verifier.get("expected_contains", [])]
    forbidden = [str(item).casefold() for item in verifier.get("forbidden_contains", [])]
    violations: list[str] = []
    if any(item and item in normalized for item in forbidden):
        violations.append("forbidden_answer_content")
    if not expected:
        score = 1.0 if final_answer.strip() else -1.0
    else:
        matched = sum(item in normalized for item in expected)
        score = (2.0 * matched / len(expected)) - 1.0
    if not final_answer.strip():
        violations.append("empty_final_answer")
    return max(-1.0, min(1.0, score)), violations
