from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.benchmark.run_9b_base_eval import aggregate, select_tasks
from scripts.benchmark.v2.validate_calibration import validate as validate_calibration
from scripts.benchmark.v2.validate_manifest import validate as validate_manifest
from studyhub_agent.benchmark_v2.development_evaluator import evaluate_development
from studyhub_agent.benchmark_v2.environment import ReplayableAgentEnvironmentV2
from studyhub_agent.benchmark_v2.hermes_runner import BenchmarkHermesRunnerV2
from studyhub_agent.benchmark_v2.schema import (
    BENCHMARK_VERSION,
    ENVIRONMENT_SCHEMA_VERSION,
    TASK_SCHEMA_VERSION,
    BenchmarkTaskV2,
    artifact_timestamp,
)
from studyhub_agent.benchmark_v2.statistics import cluster_bootstrap_interval
from studyhub_agent.benchmark_v2.web_snapshot import load_source_config, sanitize_payload

PROJECT = Path(__file__).resolve().parents[3]
PUBLIC_BENCHMARK = PROJECT / "benchmarks/studyhub-agent-v2"


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


def test_public_calibration_gate_covers_every_capability_without_sealed_tasks() -> None:
    rows = []
    for split in ("regression", "development", "calibration_challenge"):
        rows.extend(
            json.loads(line)
            for line in (PUBLIC_BENCHMARK / split / "tasks.jsonl").read_text(encoding="utf-8").splitlines()
        )

    gate = select_tasks(rows, "gate", 20260827, task_type=BenchmarkTaskV2)

    assert len(gate) == 30
    assert len({row["capability_id"] for row in gate}) == 30
    assert {row["split"] for row in gate} <= {"regression", "development", "calibration_challenge"}


def test_v2_hermes_runner_only_adapts_task_and_environment_types(tmp_path: Path) -> None:
    runner = BenchmarkHermesRunnerV2(
        hidden_root=tmp_path,
        hermes_checkout=tmp_path / "hermes",
        tokenizer_path=tmp_path / "tokenizer",
        base_url="http://127.0.0.1:30120/v1",
        api_key="ephemeral",
        model="default",
    )

    assert runner.task_type is BenchmarkTaskV2
    assert runner.environment_type is ReplayableAgentEnvironmentV2


def test_v2_aggregate_reports_cluster_aware_intervals() -> None:
    rows = [
        {
            "episode_key": f"task-{index}:0",
            "task_id": f"task-{index}",
            "capability_id": "factual_passage_retrieval" if index < 2 else "web_freshness_verification",
            "source_group_id": f"source-{index // 2}",
            "semantic_template_cluster": f"template-{index}",
            "environment_origin": "authentic_studyhub_preview" if index < 2 else "authentic_web_snapshot",
            "status": "SCORED",
            "evaluation": {
                "strict_success": index % 2 == 0,
                "diagnostic_scalar": 0.8 if index % 2 == 0 else 0.2,
            },
            "trace": {"tool_calls": []},
            "runtime": {"elapsed_seconds": 1.0},
        }
        for index in range(4)
    ]

    summary = aggregate(rows, mode="development", seed=20260827, benchmark_generation="v2")

    assert summary["benchmark_version"] == BENCHMARK_VERSION
    assert summary["mean_score"] == 0.5
    assert summary["macro_capability_strict_success"] == 0.5
    assert summary["cluster_aware_strict_success"]["source_group_id"]["effective_clusters"] == 2


def test_benchmark_runner_resolves_base_and_merged_model_lineage(tmp_path: Path) -> None:
    from scripts.benchmark.run_9b_base_eval import resolve_model_artifact

    base = tmp_path / "base"
    base.mkdir()
    (base / "config.json").write_text("{}", encoding="utf-8")
    (base / "weights.safetensors").write_bytes(b"base")
    (base / "studyhub_download_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "studyhub.model-download.v1",
                "repository": "Qwen/Qwen3.5-9B",
                "revision": "fixed",
                "weight_shards": [{"name": "weights.safetensors", "bytes": 4}],
            }
        ),
        encoding="utf-8",
    )
    identity, manifest = resolve_model_artifact(base)
    assert identity == "Qwen/Qwen3.5-9B@fixed"
    assert manifest["run_identity"] == identity

    merged = tmp_path / "merged"
    merged.mkdir()
    (merged / "config.json").write_text("{}", encoding="utf-8")
    (merged / "weights.safetensors").write_bytes(b"sft")
    (merged / "studyhub_merged_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "studyhub.merged-lora-checkpoint.v1",
                "training_stage": "sft",
                "adapter_sha256": "a" * 64,
                "weight_shards": [{"name": "weights.safetensors", "bytes": 3}],
            }
        ),
        encoding="utf-8",
    )
    identity, manifest = resolve_model_artifact(merged)
    assert identity == "StudyHub/Qwen3.5-sft@aaaaaaaaaaaaaaaa"
    assert manifest["artifact_kind"] == "merged_lora"


def test_public_calibration_record_is_bound_and_does_not_claim_difficulty() -> None:
    manifest = PUBLIC_BENCHMARK / "manifest.json"
    manifest_row = json.loads(manifest.read_text(encoding="utf-8"))
    record = json.loads(
        (PROJECT / "docs/benchmark/evidence/qwen35-9b-base-gate-20260827.json").read_text(encoding="utf-8")
    )

    if manifest_row["status"] == "FROZEN_FOR_BASELINE":
        assert record["benchmark_manifest_sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()
        assert record["builder_commit"] == manifest_row["builder_commit"]
    assert record["coverage"]["episodes_scored"] == 30
    assert record["coverage"]["capability_families"] == 30
    assert record["coverage"]["infra_excluded"] == 0
    assert record["sealed_tasks_or_graders_used"] is False
    assert record["request_audit"]["violations"] == 0
    assert record["difficulty_annotation"]["status"] == "NOT_APPLIED_INSUFFICIENT_SAMPLE"


def test_development_and_variance_evidence_is_bound_and_complete() -> None:
    manifest_path = PUBLIC_BENCHMARK / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    record = json.loads(
        (PROJECT / "docs/benchmark/evidence/qwen35-9b-base-v2-development-variance-20260827.json").read_text(
            encoding="utf-8"
        )
    )

    assert validate_calibration(record, manifest, manifest_path) == []
    assert record["development"]["episodes_scored"] == 51
    assert record["variance"]["tasks_complete"] == 35
    assert record["variance"]["episodes_scored"] == 140
    assert record["sealed_tasks_or_graders_used"] is False


def test_full_quality_gate_validates_frozen_evidence_after_finalize() -> None:
    script = (PROJECT / "scripts/benchmark/run_full_quality_gate.sh").read_text(encoding="utf-8")

    finalize = script.index('scripts/benchmark/v2/finalize.py --builder-commit "$BUILDER_COMMIT"')
    frozen_contract = script.rindex('"$PYTEST_BIN" "$calibration_contract_test"')

    assert '--deselect "$calibration_contract_test"' in script
    assert finalize < frozen_contract
    assert 'git show "HEAD:${MANIFEST_REL}"' in script


def test_errata_keeps_public_overlap_and_sealed_isolation_claims_separate() -> None:
    manifest_path = PUBLIC_BENCHMARK / "manifest.json"
    public_rows = sum(
        len((PUBLIC_BENCHMARK / split / "tasks.jsonl").read_text(encoding="utf-8").splitlines())
        for split in ("regression", "development", "calibration_challenge")
    )
    errata = (PUBLIC_BENCHMARK / "ERRATA.md").read_text(encoding="utf-8")

    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == (
        "da804b10f53dec585255598c3e256445b8ade3acf35fd8c766ca0ab4d759c88b"
    )
    assert public_rows == 73
    assert "Public prompt exact/hash overlap: `0 / 73`" in errata
    assert "Sealed task and grader content was not read" in errata
    assert "lexical/Jaccard" in errata


def test_development_exposure_ledger_never_claims_sealed_usage() -> None:
    ledger = json.loads((PUBLIC_BENCHMARK / "DEVELOPMENT_EXPOSURE_LEDGER.json").read_text(encoding="utf-8"))

    assert (
        ledger["benchmark_manifest_sha256"]
        == hashlib.sha256((PUBLIC_BENCHMARK / "manifest.json").read_bytes()).hexdigest()
    )
    assert ledger["policy"]["development_is_untouched_final_test"] is False
    assert ledger["policy"]["sealed_used"] is False
    assert all("sealed" not in row["mode"] for row in ledger["entries"])


def test_manifest_validation_defaults_to_public_only(tmp_path: Path) -> None:
    args = SimpleNamespace(
        project=PROJECT,
        public_root=PUBLIC_BENCHMARK,
        hidden_root=tmp_path / "must-not-be-read",
        require_frozen=True,
        include_hidden=False,
    )

    result = validate_manifest(args)

    assert result["status"] == "PASS"
    assert result["hidden_assets_checked"] == 0


def test_hidden_manifest_validation_requires_explicit_environment_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("STUDYHUB_ALLOW_SEALED_VALIDATION", raising=False)
    args = SimpleNamespace(
        project=PROJECT,
        public_root=PUBLIC_BENCHMARK,
        hidden_root=tmp_path / "must-not-be-read",
        require_frozen=True,
        include_hidden=True,
    )

    result = validate_manifest(args)

    assert result["status"] == "FAIL"
    assert result["hidden_assets_checked"] == 0
    assert "STUDYHUB_ALLOW_SEALED_VALIDATION=YES" in result["failures"][0]


def test_hidden_access_ledger_discloses_integrity_check_without_model_use() -> None:
    ledger = json.loads((PUBLIC_BENCHMARK / "HIDDEN_ACCESS_LEDGER.json").read_text(encoding="utf-8"))

    assert ledger["current_policy"]["default_validation"] == "PUBLIC_ONLY"
    assert ledger["current_policy"]["final_sealed_model_evaluation"] == "NOT_RUN"
    assert all(row["model_executed"] is False for row in ledger["entries"])
    assert all(row["used_for_model_selection"] is False for row in ledger["entries"])
