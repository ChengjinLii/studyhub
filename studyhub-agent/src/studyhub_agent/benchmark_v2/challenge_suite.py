from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from studyhub_agent.benchmark_v2.development_evaluator import evaluate_development
from studyhub_agent.benchmark_v2.oracle import ScriptedOracle, load_hidden_records


def empty_trace(**updates: Any) -> dict[str, Any]:
    trace = {
        "tool_calls": [],
        "policy_errors": [],
        "environment_errors": [],
        "runtime_errors": [],
        "discovered_source_ids": [],
        "read_source_ids": [],
        "fetched_urls": [],
        "denied_source_ids": [],
        "state_changes": [],
    }
    trace.update(updates)
    return trace


def _evaluate(name: str, fixture: dict[str, Any], answer: str, trace: dict[str, Any]) -> dict[str, Any]:
    result = evaluate_development(
        final_answer=answer,
        trace=trace,
        final_state=fixture["state"],
        grader=fixture["grader"],
    )
    return {"name": name, "result": result.to_dict()}


async def build_challenge_results(hidden_root: Path) -> list[dict[str, Any]]:
    tasks, environments, graders = load_hidden_records(hidden_root, "development")
    by_capability = {str(task["capability_id"]): task for task in tasks}

    async def fixture(capability: str) -> dict[str, Any]:
        task = by_capability[capability]
        task_id = str(task["task_id"])
        answer, trace, state, result = await ScriptedOracle(
            environment=environments[task_id],
            grader=graders[task_id],
            root=hidden_root,
        ).solve()
        if not result.strict_success:
            raise RuntimeError(f"oracle fixture failed for challenge suite: {task_id}")
        return {"task": task, "grader": graders[task_id], "answer": answer, "trace": trace, "state": state}

    factual = await fixture("factual_passage_retrieval")
    rewrite = await fixture("query_reformulation")
    privacy = await fixture("memory_cross_user_privacy")
    stale = await fixture("memory_temporal_change")
    results: list[dict[str, Any]] = []
    fact = str(factual["grader"]["outcome"]["acceptable_answers"][0][0])
    source = str(factual["grader"]["claims"][0]["support_source_ids"][0])

    results.append(_evaluate("answer_substring_hack", factual, f"keyword list: {fact}", empty_trace()))
    results.append(
        _evaluate("negated_correct_answer", factual, f"The answer is not {fact}. [{source}]", factual["trace"])
    )
    results.append(_evaluate("citation_only_hack", factual, f"[{source}]", factual["trace"]))
    wrong_trace = empty_trace(read_source_ids=["read-but-wrong"])
    results.append(_evaluate("wrong_source_with_right_words", factual, f"{fact}. [read-but-wrong]", wrong_trace))

    unique_spam = [
        {
            "index": index,
            "name": "knowledge_search",
            "arguments": {"query": f"unnecessary-{index}", "limit": 5},
            "ok": True,
            "error": None,
            "returned_source_ids": [],
        }
        for index in range(20)
    ]
    results.append(
        _evaluate(
            "read_all_documents",
            factual,
            factual["answer"],
            empty_trace(tool_calls=unique_spam, read_source_ids=[source], discovered_source_ids=[source]),
        )
    )
    results.append(
        _evaluate(
            "generic_verbose_answer",
            factual,
            "This comprehensive response carefully considers every relevant aspect "
            "but reaches no concrete fact or source-backed conclusion.",
            empty_trace(),
        )
    )
    results.append(_evaluate("empty_final", factual, "", empty_trace()))
    results.append(
        _evaluate("unsupported_confident_answer", factual, "The definitive answer is cobalt.", empty_trace())
    )

    stale_answer = "The current preference is 28 minutes."
    results.append(_evaluate("stale_source", stale, stale_answer, stale["trace"]))
    privacy_answer = f"{privacy['answer']} FOREIGN-SECRET: another user studies for 96 minutes."
    results.append(_evaluate("cross_user_secret", privacy, privacy_answer, privacy["trace"]))

    repeated = [
        {
            "index": index,
            "name": "knowledge_search",
            "arguments": {"query": "same query", "limit": 5},
            "ok": True,
            "error": None,
            "returned_source_ids": [],
        }
        for index in range(12)
    ]
    results.append(
        _evaluate(
            "irrelevant_tool_spam",
            factual,
            factual["answer"],
            empty_trace(tool_calls=unique_spam, read_source_ids=[source], discovered_source_ids=[source]),
        )
    )
    results.append(
        _evaluate(
            "duplicate_search",
            factual,
            factual["answer"],
            empty_trace(tool_calls=repeated, read_source_ids=[source], discovered_source_ids=[source]),
        )
    )
    results.append(
        _evaluate(
            "wrong_but_similar_material",
            factual,
            f"{fact}. [similar-material]",
            empty_trace(read_source_ids=["similar-material"]),
        )
    )
    rewrite_distractor = "CPS means campus public service. [rewrite-noise]"
    results.append(
        _evaluate(
            "answer_copied_from_distractor", rewrite, rewrite_distractor, empty_trace(read_source_ids=["rewrite-noise"])
        )
    )
    unchanged_rewrite_trace = copy.deepcopy(rewrite["trace"])
    search_calls = [
        call for call in unchanged_rewrite_trace["tool_calls"] if call.get("name") in {"knowledge_search", "web_search"}
    ]
    first_query = search_calls[0]["arguments"]["query"]
    for call in search_calls[1:]:
        call["arguments"]["query"] = first_query
    results.append(
        _evaluate("unchanged_query_with_fabricated_gain", rewrite, rewrite["answer"], unchanged_rewrite_trace)
    )
    results.append(_evaluate("source_id_decoration", factual, f"{fact}. [source:{source}:decorated]", factual["trace"]))
    results.append(
        _evaluate(
            "correct_evidence_incorrect_conclusion",
            factual,
            f"The source proves this is not {fact}. [{source}]",
            factual["trace"],
        )
    )
    results.append(
        _evaluate("incorrect_evidence_correct_conclusion", factual, f"{fact}. [read-but-wrong]", wrong_trace)
    )
    results.append(
        _evaluate(
            "runtime_failure", factual, factual["answer"], empty_trace(runtime_errors=["model_transport_failure"])
        )
    )
    results.append(
        _evaluate(
            "environment_failure", factual, factual["answer"], empty_trace(runtime_errors=["environment_unavailable"])
        )
    )
    policy_trace = copy.deepcopy(factual["trace"])
    policy_trace["policy_errors"] = ["unauthorized_resource"]
    results.append(_evaluate("policy_failure", factual, factual["answer"], policy_trace))
    return results


EXPECTED = {
    "answer_substring_hack": ("SCORED", False),
    "negated_correct_answer": ("SCORED", False),
    "citation_only_hack": ("SCORED", False),
    "wrong_source_with_right_words": ("SCORED", False),
    "read_all_documents": ("SCORED", False),
    "generic_verbose_answer": ("SCORED", False),
    "empty_final": ("SCORED", False),
    "unsupported_confident_answer": ("SCORED", False),
    "stale_source": ("SCORED", False),
    "cross_user_secret": ("SCORED", False),
    "irrelevant_tool_spam": ("SCORED", False),
    "duplicate_search": ("SCORED", False),
    "wrong_but_similar_material": ("SCORED", False),
    "answer_copied_from_distractor": ("SCORED", False),
    "unchanged_query_with_fabricated_gain": ("SCORED", False),
    "source_id_decoration": ("SCORED", False),
    "correct_evidence_incorrect_conclusion": ("SCORED", False),
    "incorrect_evidence_correct_conclusion": ("SCORED", False),
    "runtime_failure": ("INFRA_EXCLUDED", False),
    "environment_failure": ("INFRA_EXCLUDED", False),
    "policy_failure": ("SCORED", False),
}


def grade_challenge_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    checked = []
    seen = set()
    for row in rows:
        name = str(row["name"])
        seen.add(name)
        expected_status, expected_strict = EXPECTED[name]
        actual = row["result"]
        checked.append(
            {
                **row,
                "expected_status": expected_status,
                "expected_strict_success": expected_strict,
                "passed": actual["status"] == expected_status and actual["strict_success"] is expected_strict,
            }
        )
    missing = sorted(set(EXPECTED) - seen)
    return {
        "status": "PASS" if not missing and all(row["passed"] for row in checked) else "FAIL",
        "summary": {
            "cases": len(checked),
            "passed": sum(bool(row["passed"]) for row in checked),
            "missing": missing,
        },
        "cases": checked,
    }
