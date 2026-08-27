from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from studyhub_agent.benchmark_v2.development_evaluator import evaluate_development
from studyhub_agent.benchmark_v2.environment import ReplayableAgentEnvironmentV2
from studyhub_agent.benchmark_v2.schema import (
    BENCHMARK_VERSION,
    ENVIRONMENT_SCHEMA_VERSION,
    TASK_SCHEMA_VERSION,
    BenchmarkTaskV2,
    artifact_timestamp,
)
from studyhub_agent.benchmark_v2.statistics import cluster_bootstrap_interval
from studyhub_agent.benchmark_v2.web_snapshot import load_source_config, sanitize_payload


def task_row() -> dict:
    return {
        "schema_version": TASK_SCHEMA_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "task_id": "v2-test",
        "split": "development",
        "capability_id": "factual_passage_retrieval",
        "secondary_capabilities": [],
        "difficulty": "UNSCORED",
        "language": "en",
        "user_request": "Find the supported fact in the frozen source.",
        "environment_id": "v2-test",
        "available_tools": ["knowledge_search", "knowledge_read"],
        "hard_constraints": [],
        "budget_tier": "short",
        "source_group_id": "source-group-test",
        "semantic_template_cluster": "semantic-test",
        "environment_origin": "authentic_studyhub_preview",
        "difficulty_features": {
            "min_required_evidence_count": 1,
            "candidate_source_count": 2,
            "retrieval_depth": 1,
            "tool_family_count": 1,
            "state_transition_count": 0,
            "conflict_count": 0,
            "expected_horizon_band": "short",
            "distractor_count": 1,
            "ambiguity_level": 0,
        },
        "metadata": {},
    }


def test_public_schema_rejects_hidden_oracle_fields() -> None:
    assert BenchmarkTaskV2.from_dict(task_row()).task_id == "v2-test"
    leaked = task_row()
    leaked["metadata"] = {"expected_answers": ["secret"]}
    with pytest.raises(ValueError, match="oracle"):
        BenchmarkTaskV2.from_dict(leaked)


def test_artifact_timestamp_respects_source_date_epoch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")
    assert artifact_timestamp() == "1970-01-01T00:00:00+00:00"


def environment_row() -> dict:
    return {
        "schema_version": ENVIRONMENT_SCHEMA_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "task_id": "v2-test",
        "available_tools": ["knowledge_search", "knowledge_read"],
        "max_tool_calls": 4,
        "identity": {"user_id": "user-a"},
        "inline_documents": [
            {
                "source_id": "source-alpha",
                "material_id": 1,
                "title": "Signals",
                "text": "Alpha evidence describes Fourier transform conditions.",
                "access_scope": "free",
            }
        ],
        "direct_read_allowlist": [],
        "initial_state": {},
    }


def test_replay_environment_requires_search_before_read(tmp_path: Path) -> None:
    environment = ReplayableAgentEnvironmentV2(environment_row(), root=tmp_path)
    denied = json.loads(asyncio.run(environment.execute("knowledge_read", {"source_id": "source-alpha"})))
    assert denied["error"] == "source_not_discovered"
    search = json.loads(asyncio.run(environment.execute("knowledge_search", {"query": "Fourier", "limit": 5})))
    assert search["returned_source_ids"] == ["source-alpha"]
    read = json.loads(asyncio.run(environment.execute("knowledge_read", {"source_id": "source-alpha"})))
    assert read["ok"] is True
    assert environment.trace.read_source_ids == {"source-alpha"}


def grader_row() -> dict:
    return {
        "task_id": "v2-test",
        "capability_id": "factual_passage_retrieval",
        "outcome": {
            "mode": "facts",
            "acceptable_answers": [["Fourier transform"]],
            "contradiction_patterns": [],
        },
        "claims": [
            {
                "claim_id": "claim-1",
                "required": True,
                "acceptable_semantic_answers": ["Fourier transform"],
                "support_source_ids": ["source-alpha"],
                "support_facts": ["Fourier transform"],
                "support_spans": ["Fourier transform conditions"],
                "citation_required": True,
                "contradiction_patterns": [],
            }
        ],
        "evaluation_contract": {"process_constraints": {"mode": "open_path", "max_reasonable_tool_calls": 2}},
        "policy": {"forbidden_strings": []},
        "thresholds": {"task_outcome": 0.99, "answer_correctness": 0.99, "claim_support": 0.99, "process": 0.99},
        "semantic_judge": {"status": "NOT_REQUIRED"},
    }


def trace_row() -> dict:
    return {
        "tool_calls": [
            {
                "name": "knowledge_read",
                "arguments": {"source_id": "source-alpha"},
                "ok": True,
                "returned_source_ids": ["source-alpha"],
            }
        ],
        "policy_errors": [],
        "runtime_errors": [],
        "read_source_ids": ["source-alpha"],
    }


def test_evaluator_requires_supported_non_negated_claim() -> None:
    passed = evaluate_development(
        final_answer="The condition uses Fourier transform. [source-alpha]",
        trace=trace_row(),
        final_state={},
        grader=grader_row(),
    )
    assert passed.strict_success is True
    negated = evaluate_development(
        final_answer="The condition does not use Fourier transform. [source-alpha]",
        trace=trace_row(),
        final_state={},
        grader=grader_row(),
    )
    assert negated.strict_success is False


def test_cluster_bootstrap_uses_cluster_as_sampling_unit() -> None:
    rows = [
        {"cluster": "a", "value": 1.0},
        {"cluster": "a", "value": 1.0},
        {"cluster": "b", "value": 0.0},
    ]
    result = cluster_bootstrap_interval(
        rows,
        value=lambda row: float(row["value"]),
        cluster=lambda row: str(row["cluster"]),
        seed=17,
        samples=100,
    )
    assert result["effective_clusters"] == 2
    assert result["tasks"] == 3
    assert result["point"] == pytest.approx(2 / 3, abs=1e-6)


def test_web_snapshot_sanitizes_html_and_rejects_unapproved_host(tmp_path: Path) -> None:
    assert sanitize_payload(b"<html><style>x</style><body>Visible  text</body></html>", "text/html") == "Visible text"
    config = tmp_path / "sources.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": "studyhub.agentbench-web-source-config.v2",
                "sources": [
                    {
                        "source_key": "bad",
                        "split": "development",
                        "url": "https://example.com/page",
                        "publisher": "unknown",
                        "license_spdx": "MIT",
                        "license_url": "https://example.com/license",
                        "document_type": "documentation",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="allowlist"):
        load_source_config(config)
