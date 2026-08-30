from __future__ import annotations

from copy import deepcopy

from scripts.data.audit_codex_hermes_sft2_inputs import select_eligible, summarize
from studyhub_agent.trajectory.runtime_sft import trajectory_fingerprint


def _contract(*, minimum_rows: int = 1, minimum_tokens: int = 1) -> dict:
    return {
        "teacher_gate": {
            "source_dataset": "codex_hermes_teacher_v1",
            "minimum_selected_rows": minimum_rows,
            "minimum_assistant_loss_tokens": minimum_tokens,
            "allowed_quality_tiers": ["teacher_verified_complete"],
            "maximum_rows_per_source_group": 2,
            "maximum_rows_per_source_group_and_path": 1,
            "replay_only_tools": ["web_fetch"],
            "required_teacher_controller": "pinned_hermes_registry_dispatch",
            "required_teacher_interface": "codex-cli",
            "required_teacher_model": "gpt-5.6-sol",
            "required_hermes_commit": "hermes-pin",
        }
    }


def _record(
    record_id: str, *, group: str = "group-1", tool: str = "knowledge_search"
) -> dict:
    call_id = f"call-{record_id}"
    row = {
        "schema_version": "studyhub.runtime-sft-trajectory.v3",
        "id": record_id,
        "source_dataset": "codex_hermes_teacher_v1",
        "source_id": record_id,
        "group_id": group,
        "source_group_ids": [group],
        "split": "train",
        "task_family": "rag_query_rewrite_citation",
        "capability_tags": ["teacher_policy"],
        "quality_tier": "teacher_verified_complete",
        "trajectory_status": "complete",
        "runtime_native": True,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": tool,
                    "description": "test",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
            }
        ],
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": f"request {record_id}"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": tool, "arguments": {}},
                    }
                ],
            },
            {"role": "tool", "name": tool, "tool_call_id": call_id, "content": "{}"},
            {"role": "assistant", "content": "final"},
        ],
        "teacher": {
            "controller": "pinned_hermes_registry_dispatch",
            "interface": "codex-cli",
            "model": "gpt-5.6-sol",
            "hermes_commit": "hermes-pin",
            "path_signature": tool,
        },
        "verification": {
            "verifier_mode": "path_agnostic_v2",
            "invalid_citations": [],
            "disallowed_citations": [],
            "missing_answer_concept_groups": [],
            "missing_tool_groups": [],
            "provider_errors": [],
            "present_forbidden_terms": [],
        },
        "provenance": {
            "revision": "test",
            "license": "test",
            "source_url": "local://test",
        },
    }
    row["content_sha256"] = trajectory_fingerprint(row)
    return row


def test_sft2_gate_rejects_replay_tool_and_same_group_path_duplicate() -> None:
    first = _record("row-1")
    duplicate_path = _record("row-2")
    replay = _record("row-3", group="group-2", tool="web_fetch")

    selected, drops, checked = select_eligible(
        [first, duplicate_path, replay],
        contract=_contract(),
        benchmark_prompt_hashes=set(),
        count_tokens=lambda _row: (100, 25),
    )

    assert checked == 3
    assert len(selected) == 1
    assert drops["source_group_path_cap"] == 1
    assert drops["replay_only_tool:web_fetch"] == 1


def test_sft2_gate_retains_distinct_paths_and_reports_thresholds() -> None:
    first = _record("row-1")
    second = _record("row-2")
    second["teacher"] = {
        **second["teacher"],
        "path_signature": "knowledge_search->knowledge_read",
    }
    second["content_sha256"] = trajectory_fingerprint(second)
    contract = _contract(minimum_rows=2, minimum_tokens=50)

    selected, drops, checked = select_eligible(
        [first, second],
        contract=contract,
        benchmark_prompt_hashes=set(),
        count_tokens=lambda _row: (100, 25),
    )
    report = summarize(selected, checked=checked, drops=drops, contract=contract)

    assert len(selected) == 2
    assert report["status"] == "PASS"
    assert report["assistant_loss_tokens"] == 50


def test_sft2_gate_rejects_prompt_overlap_and_fingerprint_drift() -> None:
    overlap = _record("row-overlap")
    drift = deepcopy(_record("row-drift", group="group-2"))
    drift["messages"][-1]["content"] = "changed without updating fingerprint"

    selected, drops, _checked = select_eligible(
        [overlap, drift],
        contract=_contract(),
        benchmark_prompt_hashes={
            __import__(
                "scripts.data.select_runtime_sft_v3", fromlist=["candidate_prompt_hash"]
            ).candidate_prompt_hash(overlap)
        },
        count_tokens=lambda _row: (100, 25),
    )

    assert selected == []
    assert drops["public_benchmark_prompt_overlap"] == 1
    assert drops["content_sha256"] == 1


def test_sft2_gate_rejects_non_codex_teacher_identity() -> None:
    legacy_spark = _record("row-spark")
    legacy_spark["teacher"] = {
        **legacy_spark["teacher"],
        "interface": "codex-spark-cli",
        "model": "gpt-5.3-codex-spark",
    }
    legacy_spark["content_sha256"] = trajectory_fingerprint(legacy_spark)

    selected, drops, _checked = select_eligible(
        [legacy_spark],
        contract=_contract(),
        benchmark_prompt_hashes=set(),
        count_tokens=lambda _row: (100, 25),
    )

    assert selected == []
    assert drops["teacher_interface"] == 1
    assert drops["teacher_model"] == 1
