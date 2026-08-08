from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path

import pytest

from app.agentic_platform.domain.data_policy import LicenseClass
from app.services.agent_tool_loop_service import AgentToolLoopService
from ml.agentic_platform.collection.offline_guard import OfflinePilotIsolationError, assert_offline_pilot_environment
from ml.agentic_platform.collection.snapshot_pilot_data import build_pilot_manifest
from ml.agentic_platform.collection.snapshot_pilot_policy import (
    PilotObservationLedger,
    StudyHubSnapshotPolicy,
    _parse_router_json,
)
from ml.agentic_platform.collection.studyhub_snapshot_runner import run_snapshot_pilot_scenario


_ISOLATION_VARIABLES = (
    "DATABASE_URL",
    "MYSQL_URL",
    "STUDYHUB_DATABASE_URL",
    "ANTHROPIC_BASE_URL",
    "OPENAI_BASE_URL",
    "STUDYHUB_AGENTIC_MODEL_BASE_URL",
)


def test_offline_manifest_contains_the_versioned_100_scenario_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STUDYHUB_OFFLINE_PILOT_SOURCE_COMMIT", "a" * 40)
    manifest = build_pilot_manifest(trajectory_root=tmp_path / "trajectories")

    assert len(manifest.scenarios) == 100
    assert Counter(str(item.payload["family"]) for item in manifest.scenarios) == {
        "discovery": 20,
        "evidence": 20,
        "compare": 10,
        "question_pages": 10,
        "answer_pages": 10,
        "force_final": 10,
        "injection": 10,
        "restricted": 10,
    }
    assert all(item.data_policy.license_class == LicenseClass.INTERNAL_EVAL_ONLY for item in manifest.scenarios)
    assert all(item.payload["forbidden_material_ids"] == [9901] for item in manifest.scenarios)
    assert all(item.payload["source_commit_sha"] == "a" * 40 for item in manifest.scenarios)


def test_offline_guard_rejects_database_remote_provider_and_escaped_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in _ISOLATION_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "offline-pilot")
    root = tmp_path / "offline"
    trajectory_root = root / "trajectories"
    output_dir = root / "output"

    assert_offline_pilot_environment(
        provider="fixture-snapshot-guarded",
        trajectory_root=trajectory_root,
        output_dir=output_dir,
        artifact_root=root,
    )
    monkeypatch.setenv("STUDYHUB_DATABASE_URL", "mysql+pymysql://production.example/studyhub")
    with pytest.raises(OfflinePilotIsolationError, match="database_configuration_is_forbidden"):
        assert_offline_pilot_environment(
            provider="fixture-snapshot-guarded",
            trajectory_root=trajectory_root,
            output_dir=output_dir,
            artifact_root=root,
        )
    monkeypatch.delenv("STUDYHUB_DATABASE_URL")
    with pytest.raises(OfflinePilotIsolationError, match="provider_must_be_local"):
        assert_offline_pilot_environment(
            provider="openai-compatible",
            trajectory_root=trajectory_root,
            output_dir=output_dir,
            artifact_root=root,
        )
    with pytest.raises(OfflinePilotIsolationError, match="output_dir_escapes"):
        assert_offline_pilot_environment(
            provider="fixture-snapshot-guarded",
            trajectory_root=trajectory_root,
            output_dir=tmp_path / "escaped",
            artifact_root=root,
        )


def test_runtime_repair_recovers_only_an_explicit_allowlisted_read_action() -> None:
    malformed = (
        '{"actions":[{"name":"search_materials","arguments":{"filters":"大学物理",'
        '"limit":6,"query":"大学物理 免费资料 冲刺"},""],"mode":"tools"}'
    )

    recovered = _parse_router_json(malformed, repair=True)

    assert recovered is not None
    assert recovered["_runtime_recovered"] is True
    assert recovered["actions"] == [
        {
            "name": "search_materials",
            "arguments": {"query": "大学物理 免费资料 冲刺", "limit": 6},
        }
    ]
    unsupported = _parse_router_json('{"name":"delete_database","arguments":{}}', repair=True)
    assert unsupported is not None and "_runtime_recovered" not in unsupported
    assert AgentToolLoopService().parse(unsupported) is None
    assert _parse_router_json('<think>search_materials</think>', repair=True) is None


def test_runtime_rebinds_unknown_material_ids_only_to_observed_candidates() -> None:
    ledger = PilotObservationLedger()
    ledger.add_initial_search(
        query="通信原理",
        candidates=[{"material_id": 111}, {"material_id": 112}],
    )
    policy = StudyHubSnapshotPolicy(
        scenario={"query": "读取通信原理证据"},
        ledger=ledger,
        provider=object(),  # type: ignore[arg-type]
        constraints_enabled=True,
    )

    arguments = policy._normalize_skill_arguments(  # noqa: SLF001
        "materials.read_pdf_evidence",
        {"material_ids": [1, 9901], "query": "抽样定理", "max_pages": 2},
    )

    assert arguments is not None
    assert arguments["material_ids"] == [111, 112]
    assert "material_ids_rebounded_to_candidates" in policy.model_failures


def test_fixture_runner_executes_real_kernel_snapshot_skills_and_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in _ISOLATION_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "offline-pilot")
    monkeypatch.setenv("STUDYHUB_OFFLINE_PILOT_ROOT", str(tmp_path))
    manifest = build_pilot_manifest(trajectory_root=tmp_path / "trajectories")
    scenario = manifest.scenarios[20]

    outcome = asyncio.run(
        run_snapshot_pilot_scenario(
            scenario=scenario.model_dump(mode="json"),
            provider="fixture-snapshot-guarded",
            trajectory_root=manifest.trajectory_root,
            output_dir=str(tmp_path / "output"),
        )
    )

    assert outcome["status"] == "completed"
    assert int(outcome["tool_count"]) >= 2
    assert outcome["citation_valid"] is True
    assert outcome["replay_consistent"] is True
    assert list((tmp_path / "trajectories").glob("trajectory_*/manifest.json"))
    assert (tmp_path / "output" / "diagnostics" / f"{scenario.scenario_id}.json").exists()


def test_fixture_force_final_scenario_never_executes_a_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in _ISOLATION_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "offline-pilot")
    monkeypatch.setenv("STUDYHUB_OFFLINE_PILOT_ROOT", str(tmp_path))
    manifest = build_pilot_manifest(trajectory_root=tmp_path / "trajectories")
    scenario = next(item for item in manifest.scenarios if item.payload["family"] == "force_final")

    outcome = asyncio.run(
        run_snapshot_pilot_scenario(
            scenario=scenario.model_dump(mode="json"),
            provider="fixture-snapshot-guarded",
            trajectory_root=manifest.trajectory_root,
            output_dir=str(tmp_path / "output"),
        )
    )

    assert outcome["status"] == "completed"
    assert outcome["tool_count"] == 0
    assert outcome["citation_valid"] is True
