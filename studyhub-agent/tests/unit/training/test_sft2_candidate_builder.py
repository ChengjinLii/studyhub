from __future__ import annotations

from scripts.data.audit_codex_hermes_sft2_inputs import EligibleTrajectory
from scripts.data.build_qwen35_4b_sft2_candidates import build_candidate_pool
from studyhub_agent.trajectory.runtime_sft import trajectory_fingerprint


def _row(record_id: str, *, source: str, group: str, split: str = "train") -> dict:
    row = {
        "schema_version": "studyhub.runtime-sft-trajectory.v3",
        "id": record_id,
        "source_dataset": source,
        "source_id": record_id,
        "source_family": "hermes",
        "group_id": group,
        "source_group_ids": [group],
        "split": split,
        "task_family": "direct_abstention",
        "capability_tags": ["direct_abstention"],
        "quality_tier": "teacher_verified_complete",
        "trajectory_status": "complete",
        "runtime_native": False,
        "tools": [],
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": f"request {record_id}"},
            {"role": "assistant", "content": f"answer {record_id}"},
        ],
        "provenance": {
            "revision": "test",
            "license": "test",
            "source_url": "local://test",
        },
    }
    row["content_sha256"] = trajectory_fingerprint(row)
    return row


def test_candidate_builder_prioritizes_teacher_and_preserves_retention_splits() -> None:
    teacher_row = _row(
        "teacher", source="codex_hermes_teacher_v1", group="teacher-group"
    )
    teacher = [
        EligibleTrajectory(
            record=teacher_row,
            total_tokens=100,
            assistant_tokens=25,
            group_id="teacher-group",
            path_signature="DIRECT",
            stable_order="0",
        )
    ]
    retention = [
        _row(
            "retention",
            source="hermes_func_calling",
            group="retention-group",
            split="validation",
        )
    ]

    candidates, drops = build_candidate_pool(
        teacher,
        retention,
        benchmark_prompt_hashes=set(),
        prohibited_sources=set(),
    )

    assert drops == {}
    assert [row["source_family"] for row in candidates] == ["codex_teacher", "hermes"]
    assert candidates[0]["behavior_tags"] == ["direct_abstention"]
    assert candidates[0]["tool_call_count"] == 0
    assert candidates[0]["tool_turn_count"] == 0
    assert candidates[1]["split"] == "validation"


def test_candidate_builder_drops_cross_source_near_duplicate_and_prohibited_source() -> (
    None
):
    teacher_row = _row(
        "teacher", source="codex_hermes_teacher_v1", group="teacher-group"
    )
    teacher = [
        EligibleTrajectory(
            record=teacher_row,
            total_tokens=100,
            assistant_tokens=25,
            group_id="teacher-group",
            path_signature="DIRECT",
            stable_order="0",
        )
    ]
    duplicate = _row(
        "retention-duplicate", source="hermes_func_calling", group="other-group"
    )
    duplicate["messages"][0]["content"] = "different system contract"
    duplicate["messages"][1]["content"] = teacher_row["messages"][1]["content"]
    duplicate["messages"][2]["content"] = teacher_row["messages"][2]["content"]
    duplicate["content_sha256"] = trajectory_fingerprint(duplicate)
    prohibited = _row("bad", source="AgentBench_v2_all_splits", group="bad-group")

    candidates, drops = build_candidate_pool(
        teacher,
        [duplicate, prohibited],
        benchmark_prompt_hashes=set(),
        prohibited_sources={"AgentBench_v2_all_splits"},
    )

    assert len(candidates) == 1
    assert drops["deterministic_near_duplicate"] == 1
    assert drops["prohibited_source"] == 1
