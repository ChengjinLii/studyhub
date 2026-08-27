#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from studyhub_agent.benchmark_v2.development_evaluator import evaluate_development
from studyhub_agent.benchmark_v2.environment import ReplayableAgentEnvironmentV2
from studyhub_agent.benchmark_v2.oracle import (
    ScriptedOracle,
    load_hidden_records,
    oracle_state_from_assertions,
)
from studyhub_agent.benchmark_v2.schema import BENCHMARK_VERSION, artifact_timestamp, load_jsonl


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def run_oracle(hidden_root: Path, splits: list[str]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    successful: dict[str, dict[str, Any]] = {}
    for split in splits:
        tasks, environments, graders = load_hidden_records(hidden_root, split)
        for task in tasks:
            task_id = str(task["task_id"])
            row: dict[str, Any] = {
                "task_id": task_id,
                "split": split,
                "capability_id": task["capability_id"],
                "status": "ERROR",
            }
            try:
                answer, trace, state, result = await ScriptedOracle(
                    environment=environments[task_id],
                    grader=graders[task_id],
                    root=hidden_root,
                ).solve()
                row.update(
                    {
                        "status": result.status,
                        "strict_success": result.strict_success,
                        "tool_calls": result.tool_calls,
                        "realized_successful_policy_steps": result.realized_successful_policy_steps,
                        "hard_gate_reasons": list(result.hard_gate_reasons),
                        "diagnostics": result.diagnostics,
                    }
                )
                successful[task_id] = {
                    "answer": answer,
                    "trace": trace,
                    "state": state,
                    "result": result.to_dict(),
                    "grader": graders[task_id],
                    "environment": environments[task_id],
                    "task": task,
                }
            except Exception as error:  # noqa: BLE001 - report every unreachable fixture
                row["error"] = f"{type(error).__name__}: {error}"
            rows.append(row)
    scored = [row for row in rows if row.get("status") == "SCORED"]
    passed = [row for row in scored if row.get("strict_success")]
    report = {
        "schema_version": "studyhub.agentbench-oracle-report.v2",
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": artifact_timestamp(),
        "status": "PASS" if len(passed) / max(1, len(rows)) >= 0.99 else "FAIL",
        "summary": {
            "tasks": len(rows),
            "scored": len(scored),
            "strict_pass": len(passed),
            "pass_rate": len(passed) / max(1, len(rows)),
            "errors": len([row for row in rows if row.get("status") == "ERROR"]),
        },
        "by_capability": {
            capability: {
                "tasks": len(items),
                "strict_pass": sum(bool(item.get("strict_success")) for item in items),
            }
            for capability, items in sorted(_group_by(rows, "capability_id").items())
        },
        "rows": rows,
    }
    return report, successful


def _group_by(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row[key]), []).append(row)
    return grouped


def _empty_trace(**updates: Any) -> dict[str, Any]:
    value = {
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
    value.update(updates)
    return value


def run_negative_controls(successful: dict[str, dict[str, Any]]) -> dict[str, Any]:
    results: dict[str, list[bool]] = {
        "empty_answer": [],
        "random_answer": [],
        "fixed_generic_answer": [],
        "tool_spam": [],
        "citation_decoration": [],
        "wrong_source": [],
    }
    detail: list[dict[str, Any]] = []
    for task_id, fixture in successful.items():
        grader = fixture["grader"]
        state = oracle_state_from_assertions(fixture["environment"], grader)
        controls = {
            "empty_answer": ("", _empty_trace()),
            "random_answer": ("cobalt umbrella has no relationship to this task", _empty_trace()),
            "fixed_generic_answer": ("任务已经完成，相关内容如上。", _empty_trace()),
        }
        support_ids = [
            str(source_id) for claim in grader.get("claims", []) for source_id in claim.get("support_source_ids", [])
        ]
        spam_calls = [
            {
                "index": index,
                "name": "knowledge_search",
                "arguments": {"query": "repeat", "limit": 5},
                "ok": True,
                "error": None,
                "returned_source_ids": [],
            }
            for index in range(20)
        ]
        controls["tool_spam"] = (
            fixture["answer"],
            _empty_trace(tool_calls=spam_calls, read_source_ids=support_ids, discovered_source_ids=support_ids),
        )
        if any(claim.get("citation_required", True) for claim in grader.get("claims", [])):
            decorated = re.sub(r"\[[^\]]+\]", "[fabricated:source]", fixture["answer"])
            controls["citation_decoration"] = (decorated, _empty_trace())
            wrong = re.sub(r"\[[^\]]+\]", "[read-but-wrong-source]", fixture["answer"])
            controls["wrong_source"] = (
                wrong,
                _empty_trace(read_source_ids=["read-but-wrong-source"]),
            )
        for name, (answer, trace) in controls.items():
            result = evaluate_development(final_answer=answer, trace=trace, final_state=state, grader=grader)
            results[name].append(result.strict_success)
            if result.strict_success:
                detail.append({"control": name, "task_id": task_id, "diagnostics": result.to_dict()})
    summary = {
        name: {
            "evaluated": len(values),
            "strict_pass": sum(values),
            "strict_pass_rate": sum(values) / max(1, len(values)),
        }
        for name, values in results.items()
    }
    return {
        "schema_version": "studyhub.agentbench-negative-controls.v2",
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": artifact_timestamp(),
        "status": "PASS" if all(row["strict_pass"] == 0 for row in summary.values()) else "FAIL",
        "summary": summary,
        "unexpected_passes": detail,
    }


async def run_metamorphic(hidden_root: Path, successful: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []

    def record(name: str, passed: bool, detail: Any) -> None:
        cases.append({"name": name, "passed": passed, "detail": detail})

    state_fixture = next(
        value for value in successful.values() if value["task"]["capability_id"] == "state_function_calling"
    )
    env_a = ReplayableAgentEnvironmentV2(copy.deepcopy(state_fixture["environment"]), root=hidden_root)
    env_b = ReplayableAgentEnvironmentV2(copy.deepcopy(state_fixture["environment"]), root=hidden_root)
    assertion = state_fixture["grader"]["outcome"]["state_assertions"]
    topic = assertion[0]["path"].split(".")[1]
    minutes = next(item["value"] for item in assertion if item["path"].endswith("weekly_minutes"))
    material_id = next(item["value"] for item in assertion if item["path"].endswith("resource_ids"))
    result_a = json.loads(
        await env_a.execute(
            "study_plan_update",
            {"topic": topic, "weekly_minutes": minutes, "resource_ids": [material_id]},
        )
    )
    result_b = json.loads(
        await env_b.execute(
            "study_plan_update",
            {"resource_ids": [material_id], "weekly_minutes": minutes, "topic": topic},
        )
    )
    record(
        "json_key_order",
        result_a == result_b and env_a.state_snapshot() == env_b.state_snapshot(),
        [result_a, result_b],
    )

    retrieval_fixture = next(
        value for value in successful.values() if value["task"]["capability_id"] == "factual_passage_retrieval"
    )
    target_id = retrieval_fixture["grader"]["claims"][0]["support_source_ids"][0]
    target_doc = next(
        row
        for row in load_jsonl(hidden_root / "corpora" / f"{retrieval_fixture['task']['split']}.jsonl")
        if str(row["source_id"]) == str(target_id)
    )
    query = str(target_doc["text"])[:180]
    env_default = ReplayableAgentEnvironmentV2(copy.deepcopy(retrieval_fixture["environment"]), root=hidden_root)
    env_explicit = ReplayableAgentEnvironmentV2(copy.deepcopy(retrieval_fixture["environment"]), root=hidden_root)
    default_result = json.loads(await env_default.execute("knowledge_search", {"query": query}))
    explicit_result = json.loads(await env_explicit.execute("knowledge_search", {"query": f"  {query}  ", "limit": 5}))
    record(
        "equivalent_argument_formatting",
        default_result["returned_source_ids"] == explicit_result["returned_source_ids"],
        {"default": default_result["returned_source_ids"], "explicit": explicit_result["returned_source_ids"]},
    )

    shuffled = copy.deepcopy(retrieval_fixture["environment"])
    distractor = {
        "source_id": "metamorphic:irrelevant",
        "material_id": 123456789,
        "title": "Unrelated dining schedule",
        "text": "Cafeteria opening hours and bus routes.",
        "access_scope": "free",
    }
    shuffled["inline_documents"] = [distractor, *reversed(shuffled.get("inline_documents", []))]
    env_distractor = ReplayableAgentEnvironmentV2(shuffled, root=hidden_root)
    distractor_result = json.loads(await env_distractor.execute("knowledge_search", {"query": query, "limit": 5}))
    record("irrelevant_distractor_insertion", target_id in distractor_result["returned_source_ids"], distractor_result)

    corpus_environment = copy.deepcopy(retrieval_fixture["environment"])
    original_corpus = load_jsonl(hidden_root / "corpora" / f"{retrieval_fixture['task']['split']}.jsonl")
    reversed_environment = copy.deepcopy(corpus_environment)
    env_order_a = ReplayableAgentEnvironmentV2(corpus_environment, root=hidden_root)
    env_order_b = ReplayableAgentEnvironmentV2(reversed_environment, root=hidden_root)
    env_order_b._documents = {str(row["source_id"]): row for row in reversed(original_corpus)}  # noqa: SLF001
    from studyhub_agent.benchmark_v1.environment import ReplayIndex

    env_order_b._knowledge_index = ReplayIndex(env_order_b._documents.values())  # noqa: SLF001
    order_a = json.loads(await env_order_a.execute("knowledge_search", {"query": query, "limit": 5}))
    order_b = json.loads(await env_order_b.execute("knowledge_search", {"query": query, "limit": 5}))
    record("source_order_shuffle", order_a["returned_source_ids"] == order_b["returned_source_ids"], [order_a, order_b])

    paraphrase = f"{target_doc['title']} {retrieval_fixture['grader']['claims'][0]['support_facts'][0]}"
    paraphrased = json.loads(await env_default.execute("knowledge_search", {"query": paraphrase, "limit": 12}))
    record("query_paraphrase_reachability", target_id in paraphrased["returned_source_ids"], paraphrased)

    multi_fixture = next(value for value in successful.values() if len(value["grader"].get("claims", [])) >= 2)
    reversed_answer = " ".join(reversed(re.findall(r"[^.]+\.", multi_fixture["answer"])))
    reversed_result = evaluate_development(
        final_answer=reversed_answer,
        trace=multi_fixture["trace"],
        final_state=multi_fixture["state"],
        grader=multi_fixture["grader"],
    )
    record("citation_claim_order", reversed_result.strict_success, reversed_result.to_dict())

    multistep = next(
        value for value in successful.values() if value["task"]["capability_id"] == "state_multistep_postcondition"
    )
    reordered_trace = copy.deepcopy(multistep["trace"])
    reordered_trace["tool_calls"] = list(reversed(reordered_trace["tool_calls"]))
    reordered_result = evaluate_development(
        final_answer=multistep["answer"],
        trace=reordered_trace,
        final_state=multistep["state"],
        grader=multistep["grader"],
    )
    record("equivalent_state_action_order", reordered_result.strict_success, reordered_result.to_dict())

    direct = next(
        value for value in successful.values() if value["task"]["capability_id"] == "direct_answer_tool_relevance"
    )
    direct_reformatted = evaluate_development(
        final_answer=f"Result: {direct['answer']}\n",
        trace=direct["trace"],
        final_state=direct["state"],
        grader=direct["grader"],
    )
    record("answer_formatting", direct_reformatted.strict_success, direct_reformatted.to_dict())

    return {
        "schema_version": "studyhub.agentbench-metamorphic-report.v2",
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": artifact_timestamp(),
        "status": "PASS" if all(case["passed"] for case in cases) else "FAIL",
        "summary": {"cases": len(cases), "passed": sum(case["passed"] for case in cases)},
        "cases": cases,
    }


def run_shortcut_probe(hidden_root: Path) -> dict[str, Any]:
    public_root = hidden_root.parents[2] / "benchmarks/studyhub-agent-v2"
    split_paths = {
        "regression": public_root / "regression/tasks.jsonl",
        "development": public_root / "development/tasks.jsonl",
        "calibration_challenge": public_root / "calibration_challenge/tasks.jsonl",
        "sealed_a": hidden_root / "tasks/sealed_a.jsonl",
        "sealed_b": hidden_root / "tasks/sealed_b.jsonl",
    }
    tasks = {split: load_jsonl(path) for split, path in split_paths.items()}
    graders = {
        split: {str(row["task_id"]): row for row in load_jsonl(hidden_root / "graders" / f"{split}.jsonl")}
        for split in split_paths
    }
    leaked_task_ids = []
    content_request_leaks = []
    partial_answer_mentions = []
    answer_signatures: Counter[str] = Counter()
    public_oracle_fields = []
    for split, rows in tasks.items():
        for task in rows:
            grader = graders[split][str(task["task_id"])]
            facts = [str(group[0]) for group in grader.get("outcome", {}).get("acceptable_answers", []) if group]
            if facts:
                signature = hashlib.sha256(json.dumps(facts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[
                    :16
                ]
                answer_signatures[signature] += 1
            for fact in facts:
                normalized = re.sub(r"[^0-9a-z㐀-鿿]+", "", fact.casefold())
                if normalized and normalized in re.sub(r"[^0-9a-z㐀-鿿]+", "", str(task["task_id"]).casefold()):
                    leaked_task_ids.append([task["task_id"], fact])
            if task["capability_id"] in {
                "factual_passage_retrieval",
                "cross_chunk_synthesis",
                "authentic_web_research",
                "source_disambiguation_ood",
            }:
                request = str(task["user_request"]).casefold()
                mentioned = [fact for fact in facts if len(fact) >= 5 and fact.casefold() in request]
                if mentioned:
                    partial_answer_mentions.append([task["task_id"], mentioned])
                if facts and len(mentioned) == len(facts):
                    content_request_leaks.append([task["task_id"], mentioned])
            forbidden = {
                "acceptable_semantic_answers",
                "support_facts",
                "support_spans",
                "grader",
                "oracle_answer",
            }
            exposed = forbidden & set(task)
            if exposed:
                public_oracle_fields.append([task["task_id"], sorted(exposed)])
    total = sum(len(rows) for rows in tasks.values())
    max_signature = max(answer_signatures.values(), default=0)
    checks = {
        "task_id_answer_leakage_zero": not leaked_task_ids,
        "content_request_answer_leakage_zero": not content_request_leaks,
        "public_oracle_fields_zero": not public_oracle_fields,
        "difficulty_not_ordinal": all(task["difficulty"] == "UNSCORED" for rows in tasks.values() for task in rows),
        "largest_answer_signature_at_most_ten_percent": max_signature / max(1, total) <= 0.10,
        "semantic_template_ids_unique": len(
            {task["semantic_template_cluster"] for rows in tasks.values() for task in rows}
        )
        == total,
    }
    return {
        "schema_version": "studyhub.agentbench-shortcut-probe.v2",
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": artifact_timestamp(),
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "statistics": {
            "tasks": total,
            "unique_answer_signatures": len(answer_signatures),
            "largest_answer_signature": max_signature,
            "largest_answer_signature_share": max_signature / max(1, total),
        },
        "findings": {
            "task_id_answer_leakage": leaked_task_ids,
            "content_request_answer_leakage": content_request_leaks,
            "partial_answer_mentions_diagnostic": partial_answer_mentions,
            "public_oracle_fields": public_oracle_fields,
        },
    }


def write_report(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--hidden-root",
        type=Path,
        default=project / "artifacts/benchmark-v2/studyhub-agent-v2",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=project / "artifacts/benchmark-v2/self-tests",
    )
    parser.add_argument(
        "--public-summary",
        type=Path,
        default=project / "benchmarks/studyhub-agent-v2/self-test-summary.json",
    )
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> int:
    hidden_root = args.hidden_root.resolve()
    oracle, successful = await run_oracle(hidden_root, ["regression", "development", "calibration_challenge"])
    negative = run_negative_controls(successful)
    metamorphic = await run_metamorphic(hidden_root, successful)
    shortcut = run_shortcut_probe(hidden_root)
    reports = {
        "oracle-reachability-report.json": oracle,
        "negative-control-report.json": negative,
        "metamorphic-test-report.json": metamorphic,
        "shortcut-probe-report.json": shortcut,
    }
    output_root = args.output_root.resolve()
    for name, report in reports.items():
        write_report(output_root / name, report)
    status = "PASS" if all(report["status"] == "PASS" for report in reports.values()) else "FAIL"
    summary = {
        "schema_version": "studyhub.agentbench-self-test-summary.v2",
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": artifact_timestamp(),
        "status": status,
        "oracle": oracle["summary"],
        "negative_controls": negative["summary"],
        "metamorphic": metamorphic["summary"],
        "shortcut": {"checks": shortcut["checks"], **shortcut["statistics"]},
        "artifact_hashes": {name: sha256(output_root / name) for name in reports},
    }
    write_report(args.public_summary.resolve(), summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 1


def main() -> int:
    return asyncio.run(async_main(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
