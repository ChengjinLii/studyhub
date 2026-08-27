#!/usr/bin/env python3
"""Dependency-light smoke checks without generating external benchmark scores."""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from external_benchmarks.adapters import (  # noqa: E402 - standalone script bootstraps project root
    OfficialInvocation,
    OpenAICompatiblePolicyAdapter,
)
from external_benchmarks.registry import load_registry  # noqa: E402 - standalone script bootstraps project root
from external_benchmarks.result_schema import (  # noqa: E402 - standalone script bootstraps project root
    GenerationRequest,
    ModelEndpointConfig,
)


def load_json_records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        value = json.loads(text)
        return [row for row in value if isinstance(row, dict)]
    rows = []
    for line in text.splitlines():
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def mock_adapter_check() -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def transport(url: str, body: bytes, headers: dict[str, str], timeout: float) -> dict[str, Any]:
        seen.update(
            {"url": url, "payload": json.loads(body), "has_auth": "Authorization" in headers, "timeout": timeout}
        )
        return {
            "id": "mock-response",
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": '{"query":"safe"}'},
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        }

    environment_name = "STUDYHUB_EXTERNAL_SMOKE_TOKEN"
    previous = os.environ.get(environment_name)
    os.environ[environment_name] = "local-mock-token"
    try:
        adapter = OpenAICompatiblePolicyAdapter(
            ModelEndpointConfig(
                base_url="http://127.0.0.1:30000/v1",
                model="studyhub-smoke-model",
                api_key_env=environment_name,
                timeout_seconds=5,
            ),
            transport=transport,
        )
        result = adapter.generate(
            GenerationRequest(
                messages=({"role": "user", "content": "smoke"},),
                tools=(
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "description": "fixture",
                            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
                        },
                    },
                ),
                seed=20260827,
            )
        )
    finally:
        if previous is None:
            os.environ.pop(environment_name, None)
        else:
            os.environ[environment_name] = previous
    passed = (
        seen.get("url") == "http://127.0.0.1:30000/v1/chat/completions"
        and seen.get("has_auth") is True
        and seen.get("payload", {}).get("seed") == 20260827
        and len(result.tool_trace) == 1
        and result.tool_trace[0].arguments == {"query": "safe"}
        and result.usage.total_tokens == 18
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "tool_calls": len(result.tool_trace),
        "total_tokens": result.usage.total_tokens,
    }


def compile_path(path: Path) -> None:
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def smoke_bfcl(source: Path) -> dict[str, Any]:
    root = source / "berkeley-function-call-leaderboard"
    categories = sorted((root / "bfcl_eval/data").glob("BFCL_v4_*.json"))
    sample = load_json_records(root / "bfcl_eval/data/BFCL_v4_simple_python.json")
    compile_path(root / "bfcl_eval/eval_checker/eval_runner.py")
    generate = OfficialInvocation.bfcl_generate(
        source,
        model="studyhub-qwen",
        categories=("simple_python",),
        result_dir="result/studyhub-smoke",
    )
    evaluate = OfficialInvocation.bfcl_evaluate(
        source,
        model="studyhub-qwen",
        categories=("simple_python",),
        result_dir="result/studyhub-smoke",
    )
    return {
        "status": "SETUP_READY",
        "task_discovery": {"v4_category_files": len(categories), "sample_records": len(sample)},
        "official_invocation": {"generate": list(generate.command), "evaluate": list(evaluate.command)},
        "official_import": "NOT_RUN_DEPENDENCIES_NOT_INSTALLED",
        "model_score_generated": False,
    }


def smoke_tau2(source: Path) -> dict[str, Any]:
    domains = {}
    for domain in ("airline", "retail", "telecom", "banking_knowledge"):
        rows = load_json_records(source / f"data/tau2/domains/{domain}/tasks.json")
        domains[domain] = len(rows)
    compile_path(source / "src/tau2/evaluator/evaluator.py")
    invocation = OfficialInvocation.tau2_run(
        source,
        domain="airline",
        agent_model="studyhub-qwen",
        user_model="studyhub-user-simulator",
        task_ids=("0",),
    )
    return {
        "status": "SETUP_READY",
        "task_discovery": {"domains": domains, "total": sum(domains.values())},
        "official_invocation": list(invocation.command),
        "official_import": "NOT_RUN_DEPENDENCIES_NOT_INSTALLED",
        "official_semantics": "DB/COMMUNICATE outcome; reference actions are diagnostic unless ACTION gates reward",
        "model_score_generated": False,
    }


def smoke_browsecomp(source: Path) -> dict[str, Any]:
    qrel_counts = {}
    for name in ("qrel_evidence.txt", "qrel_golds.txt"):
        qrel_counts[name] = sum(
            1 for line in (source / "topics-qrels" / name).read_text(encoding="utf-8").splitlines() if line
        )
    compile_path(source / "scripts_evaluation/evaluate_run.py")
    invocation = OfficialInvocation.browsecomp_evaluate(source, input_dir=Path("runs/studyhub-smoke"))
    return {
        "status": "SETUP_READY",
        "task_discovery": {"bundled_qrel_rows": qrel_counts},
        "official_invocation": list(invocation.command),
        "dataset_download": "NOT_RUN_LARGE_MANUAL_ARTIFACT",
        "official_evaluation": "SKIPPED_NO_GPU",
        "model_score_generated": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=PROJECT_ROOT / "external_benchmarks/registry.yaml")
    parser.add_argument("--lock", type=Path, default=PROJECT_ROOT / "external_benchmarks/lock.json")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "external_benchmarks/smoke-status.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    registry = load_registry(args.registry)
    lock = json.loads(args.lock.read_text(encoding="utf-8"))
    adapter = mock_adapter_check()
    results: dict[str, Any] = {}
    for name, row in registry["benchmarks"].items():
        locked = lock["benchmarks"][name]
        if row["license"]["status"] != "verified":
            results[name] = {
                "status": "LICENSE_REVIEW_REQUIRED",
                "source_exported": False,
                "official_evaluation": "NOT_RUN",
                "model_score_generated": False,
            }
            continue
        source = PROJECT_ROOT / str(locked["source_path"])
        if not source.is_dir():
            results[name] = {"status": "FAILED", "reason": "source cache missing", "model_score_generated": False}
        elif name == "bfcl":
            results[name] = smoke_bfcl(source)
        elif name == "tau2":
            results[name] = smoke_tau2(source)
        elif name == "browsecomp_plus":
            results[name] = smoke_browsecomp(source)
        else:
            results[name] = {"status": "FAILED", "reason": "no smoke adapter", "model_score_generated": False}
    failed = adapter["status"] != "PASS" or any(row["status"] == "FAILED" for row in results.values())
    report = {
        "schema_version": "studyhub.external-benchmark-smoke.v1",
        "portfolio_version": registry["portfolio_version"],
        "status": "FAIL" if failed else "PASS",
        "adapter_mock": adapter,
        "benchmarks": results,
        "note": "No external model score was generated by this smoke test.",
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
