from __future__ import annotations

from scripts.data.build_open_rl_tasks import select_qasper_annotation
from training.rl.budget_contract import (
    CONTROLLED_TASK_MAX_TOOL_CALLS,
    RUNTIME_MAX_MODEL_TURNS,
    make_budget_contract,
    search_budget_contract,
    validate_task_budget,
)


def test_qasper_canonical_annotation_keeps_answer_and_evidence_bound() -> None:
    documents = [
        {"source_id": "src-a", "title": "A", "text": "Evidence for answer alpha."},
        {"source_id": "src-b", "title": "B", "text": "Evidence for answer beta."},
    ]
    entries = [
        {
            "annotation_id": "annotation-a",
            "answer": {
                "unanswerable": False,
                "free_form_answer": "alpha",
                "evidence": ["Evidence for answer alpha."],
            },
        },
        {
            "annotation_id": "annotation-b",
            "answer": {
                "unanswerable": False,
                "free_form_answer": "beta",
                "evidence": ["Evidence for answer beta."],
            },
        },
    ]

    selected = select_qasper_annotation(entries, documents)

    assert selected is not None
    expected_source = {"alpha": ["src-a"], "beta": ["src-b"]}
    assert selected["gold_source_ids"] == expected_source[selected["expected_answer"]]
    assert len(selected["gold_source_ids"]) == 1


def test_qasper_canonical_annotation_rejects_infeasible_evidence_union() -> None:
    documents = [
        {"source_id": f"src-{index}", "title": str(index), "text": f"Evidence {index}."}
        for index in range(6)
    ]
    entries = [
        {
            "annotation_id": "too-large",
            "answer": {
                "unanswerable": False,
                "free_form_answer": "large",
                "evidence": [f"Evidence {index}." for index in range(5)],
            },
        },
        {
            "annotation_id": "feasible",
            "answer": {
                "unanswerable": False,
                "free_form_answer": "small",
                "evidence": ["Evidence 5."],
            },
        },
    ]

    selected = select_qasper_annotation(entries, documents)

    assert selected is not None
    assert selected["annotation_id"] == "feasible"
    assert selected["budget_contract"]["reference_model_turns"] == 3


def test_budget_contract_accepts_controlled_function_trajectory() -> None:
    task = {
        "task_id": "function-task",
        "max_steps": RUNTIME_MAX_MODEL_TURNS,
        "max_tool_calls": CONTROLLED_TASK_MAX_TOOL_CALLS,
    }
    verifier = {
        "family": "function_calling",
        "expected_calls": [{"name": "a"}, {"name": "b"}],
        "budget_contract": make_budget_contract(
            reference_model_turns=3,
            required_tool_calls=2,
        ),
    }

    assert validate_task_budget(task, verifier) == []


def test_budget_contract_rejects_search_task_beyond_runtime_turns() -> None:
    gold_sources = [f"src-{index}" for index in range(5)]
    task = {
        "task_id": "search-task",
        "max_steps": RUNTIME_MAX_MODEL_TURNS,
        "max_tool_calls": CONTROLLED_TASK_MAX_TOOL_CALLS,
    }
    verifier = {
        "family": "evidence_grounding",
        "gold_source_ids": gold_sources,
        "budget_contract": search_budget_contract(gold_sources),
    }

    failures = validate_task_budget(task, verifier)

    assert any("cannot finish within model turns" in failure for failure in failures)
