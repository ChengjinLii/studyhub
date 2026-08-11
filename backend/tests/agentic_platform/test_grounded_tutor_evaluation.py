from __future__ import annotations

from ml.agentic_platform.sft.evaluate_grounded_tutor import (
    _answer_bigram_f1,
    _score_tutor,
)


def _target() -> dict[str, object]:
    return {
        "mode": "final",
        "task_context": {},
        "answer": "当前证据只能支持这一页的定义和公式，不能外推未展示页面。",
        "recommendations": [],
        "evidence_sources": [
            {
                "chunk_id": "18:preview_vlm:2:abc",
                "material_id": 18,
                "page": 2,
                "title": "通信原理讲义",
            }
        ],
        "followup_questions": [],
    }


def test_tutor_score_accepts_exact_grounded_final() -> None:
    expected = _target()
    scores = _score_tutor(
        expected=expected,
        predicted=dict(expected),
        family="evidence_scope_v1",
        generated="generated safe JSON",
    )

    assert scores["contract_valid"] is True
    assert scores["citations_exact"] is True
    assert scores["strict_grounded_pass"] is True
    assert scores["answer_bigram_f1"] == 1.0


def test_tutor_score_rejects_fabricated_citation_and_action() -> None:
    expected = _target()
    predicted = dict(expected)
    predicted["evidence_sources"] = [
        {
            "chunk_id": "999:private:1",
            "material_id": 999,
            "page": 1,
            "title": "未知资料",
        }
    ]
    predicted["actions"] = [{"name": "write_material", "arguments": {}}]
    scores = _score_tutor(
        expected=expected,
        predicted=predicted,
        family="evidence_scope_v1",
        generated="generated safe JSON",
    )

    assert scores["citations_allowed"] is False
    assert scores["no_tool_actions"] is False
    assert scores["strict_grounded_pass"] is False


def test_answer_similarity_is_bounded() -> None:
    assert _answer_bigram_f1("相同答案", "相同答案") == 1.0
    assert 0.0 <= _answer_bigram_f1("部分相同答案", "相同答案但有变化") <= 1.0
