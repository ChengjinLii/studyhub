from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from external_benchmarks.adapters import OfficialInvocation, OpenAICompatiblePolicyAdapter
from external_benchmarks.registry import load_registry
from external_benchmarks.result_schema import (
    ExternalBenchmarkResult,
    GenerationRequest,
    ModelEndpointConfig,
)

PROJECT = Path(__file__).resolve().parents[3]


def test_registry_pins_official_revisions_and_license_gate() -> None:
    registry = load_registry(PROJECT / "external_benchmarks/registry.yaml")
    assert set(registry["benchmarks"]) == {"bfcl", "tau2", "deepresearch_bench_ii", "browsecomp_plus"}
    assert all(len(row["revision"]["resolved_commit"]) == 40 for row in registry["benchmarks"].values())
    deepresearch = registry["benchmarks"]["deepresearch_bench_ii"]
    assert deepresearch["license"]["status"] == "unconfirmed"
    assert deepresearch["export_allowed"] is False


def test_openai_adapter_serializes_and_parses_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def transport(url: str, body: bytes, headers: dict[str, str], timeout: float) -> dict:
        captured.update(url=url, body=json.loads(body), has_auth="Authorization" in headers, timeout=timeout)
        return {
            "id": "response-1",
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {"name": "search", "arguments": '{"query":"signals"}'},
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
        }

    monkeypatch.setenv("EXTERNAL_TEST_KEY", "fixture-only")
    adapter = OpenAICompatiblePolicyAdapter(
        ModelEndpointConfig("http://127.0.0.1:30000/v1", "qwen", "EXTERNAL_TEST_KEY", 3),
        transport=transport,
    )
    result = adapter.generate(
        GenerationRequest(
            messages=({"role": "user", "content": "find signals"},),
            tools=(
                {
                    "type": "function",
                    "function": {"name": "search", "parameters": {"type": "object"}},
                },
            ),
            seed=17,
        )
    )
    assert captured == {
        "url": "http://127.0.0.1:30000/v1/chat/completions",
        "body": {
            "model": "qwen",
            "messages": [{"role": "user", "content": "find signals"}],
            "temperature": 0.0,
            "max_tokens": 4096,
            "tools": [{"type": "function", "function": {"name": "search", "parameters": {"type": "object"}}}],
            "tool_choice": "auto",
            "seed": 17,
        },
        "has_auth": True,
        "timeout": 3,
    }
    assert result.tool_trace[0].name == "search"
    assert result.tool_trace[0].arguments == {"query": "signals"}
    assert result.usage.total_tokens == 9
    assert "fixture-only" not in json.dumps(result, default=str)


def test_adapter_requires_key_without_exposing_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_EXTERNAL_KEY", raising=False)
    adapter = OpenAICompatiblePolicyAdapter(
        ModelEndpointConfig("http://localhost:8000/v1", "qwen", "MISSING_EXTERNAL_KEY")
    )
    with pytest.raises(RuntimeError, match="MISSING_EXTERNAL_KEY"):
        adapter.generate(GenerationRequest(messages=({"role": "user", "content": "test"},)))


def test_official_invocations_preserve_upstream_entrypoints(tmp_path: Path) -> None:
    bfcl = OfficialInvocation.bfcl_evaluate(
        tmp_path,
        model="studyhub-qwen",
        categories=("simple_python",),
        result_dir="result/smoke",
    )
    tau2 = OfficialInvocation.tau2_run(
        tmp_path,
        domain="retail",
        agent_model="studyhub-qwen",
        user_model="user-simulator",
    )
    assert bfcl.command[:2] == ("bfcl", "evaluate")
    assert "--partial-eval" in bfcl.command
    assert tau2.command[:4] == ("uv", "run", "tau2", "run")
    assert "--domain" in tau2.command
    with pytest.raises(ValueError, match="unsupported core tau2 domain"):
        OfficialInvocation.tau2_run(
            tmp_path,
            domain="voice",
            agent_model="studyhub-qwen",
            user_model="user-simulator",
        )


def test_result_schema_keeps_raw_metric_identity() -> None:
    result = ExternalBenchmarkResult(
        benchmark="bfcl",
        benchmark_version="v4",
        model="qwen",
        model_revision="base",
        adapter_revision="adapter-v1",
        run_id="run-1",
        raw_metric_name="overall_accuracy",
        raw_metric_value=0.5,
        status="COMPLETED",
    )
    assert result.to_dict()["raw_metric_name"] == "overall_accuracy"
    assert "normalized_score" not in result.to_dict()


def test_config_rejects_embedded_credentials() -> None:
    with pytest.raises(ValueError, match="credentials"):
        ModelEndpointConfig("https://user:secret@example.com/v1", "qwen")
    assert "OPENAI_API_KEY" not in os.environ or isinstance(os.environ["OPENAI_API_KEY"], str)
