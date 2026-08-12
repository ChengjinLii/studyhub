from __future__ import annotations

import json

import pytest

from ml.agentic_platform.rl.environment import RouterRLEnvironment
from ml.agentic_platform.rl.diagnose_constraint_gap import diagnose
from ml.agentic_platform.rl.evaluate import summarize_rows
from ml.agentic_platform.rl.gate import assess_candidate, assess_training_run
from ml.agentic_platform.rl.judge_calibration import teacher_preferred_output, teacher_rejected_output
from ml.agentic_platform.rl.reward import RouterRewardPolicy, group_relative_advantages, score_double_ledger
from ml.agentic_platform.rl.spec import RouterRLSpecError, RouterRLState, audit_states, canonical_json


def _state(
    *,
    state_id: str = "episode-1-s0",
    episode_id: str = "episode-1",
    split: str = "train",
    step_index: int = 0,
    max_steps: int = 1,
    expected_mode: str = "tools",
    expected_tools: list[str] | None = None,
    next_state_id: str | None = None,
    terminal: bool = True,
    material_ids: list[int] | None = None,
) -> RouterRLState:
    material_ids = material_ids or [18]
    payload = {
        "current_user_query": "读取资料 18 第2页的通信原理证据。",
        "force_final": False,
        "budget": {
            "remaining_rounds": 2,
            "remaining_tool_calls": 3,
            "remaining_search_calls": 1,
            "remaining_candidate_slots": 8,
        },
        "task_context": {"course_terms": ["通信原理"]},
        "tool_observations": [
            {
                "tool": "inspect_materials",
                "result": {"materials": [{"id": material_id, "title": f"资料{material_id}", "free": True} for material_id in material_ids]},
            }
        ],
        "search_history": [],
    }
    mapping = {
        "schema_version": "studyhub.agent.router_rl.state.v1",
        "state_id": state_id,
        "episode_id": episode_id,
        "split": split,
        "family": "read_evidence" if expected_mode == "tools" else "grounded_final",
        "step_index": step_index,
        "max_steps": max_steps,
        "request_payload": payload,
        "messages": [
            {"role": "system", "content": "只读 Router"},
            {"role": "user", "content": canonical_json(payload)},
        ],
        "reward_rubric": {
            "expected_mode": expected_mode,
            "expected_tools": expected_tools if expected_tools is not None else (["read_pdf_evidence"] if expected_mode == "tools" else []),
            "query_terms": ["通信原理"] if expected_mode == "tools" else [],
            "trusted_material_ids": material_ids,
            "explicit_pages": [2] if expected_mode == "tools" else [],
            "answer_terms": ["通信原理"] if expected_mode == "final" else [],
            "evidence_required": expected_mode == "final",
        },
        "source_material_ids": material_ids,
        "next_state_id": next_state_id,
        "terminal": terminal,
        "training_eligible": split == "train",
        "training_export_allowed": split == "train",
        "isolation": {
            "production_api_called": False,
            "production_database_accessed": False,
            "paid_material_used": False,
            "final_holdout_read": False,
        },
        "provenance": {"source": "frozen_free_public_backup"},
    }
    return RouterRLState.from_mapping(mapping)


def test_reward_prefers_teacher_semantic_action() -> None:
    state = _state()
    policy = RouterRewardPolicy()

    preferred = policy.score(teacher_preferred_output(state), state)
    rejected = policy.score(teacher_rejected_output(state), state)

    assert preferred.policy_reward > rejected.policy_reward
    assert preferred.components["tool_choice"] == 1.0
    assert preferred.hard_gates["explicit_pages_preserved"] is True


def test_deterministic_id_protection_is_a_gate_not_a_reward() -> None:
    state = _state(material_ids=[18])
    valid = teacher_preferred_output(state)
    invalid = json.loads(json.dumps(valid))
    invalid["actions"][0]["arguments"]["material_ids"] = [999]
    policy = RouterRewardPolicy()

    valid_score = policy.score(valid, state)
    invalid_score = policy.score(invalid, state)

    assert valid_score.policy_reward == invalid_score.policy_reward
    assert valid_score.hard_gates["trusted_references"] is True
    assert invalid_score.hard_gates["trusted_references"] is False


def test_double_ledger_exposes_constraint_dependency() -> None:
    state = _state()
    unsafe_ids = {
        "mode": "tools",
        "progress": "读取证据中",
        "task_context": {},
        "actions": [
            {
                "name": "read_pdf_evidence",
                "arguments": {"material_ids": [999], "query": "通信原理", "max_pages": 99, "page_numbers": [99]},
            }
        ],
    }

    ledger = score_double_ledger(unsafe_ids, state)

    assert ledger.raw.hard_gates["trusted_references"] is False
    assert ledger.executable.hard_gates["trusted_references"] is True
    assert ledger.executable_value["actions"][0]["arguments"]["material_ids"] == [18]
    assert ledger.constraint_corrections


def test_sensitive_gate_allows_safe_refusal_but_rejects_an_actual_code() -> None:
    state = _state(expected_mode="final", expected_tools=[])
    policy = RouterRewardPolicy()
    base = {
        "mode": "final",
        "task_context": {},
        "answer": "不能绕过权限，也不会读取或泄露提取码。",
        "recommendations": [],
        "evidence_sources": [],
        "followup_questions": [],
    }

    assert policy.score(base, state).hard_gates["sensitive_output_absent"] is True
    leaked = {**base, "answer": "提取码：a1b2"}
    assert policy.score(leaked, state).hard_gates["sensitive_output_absent"] is False


def test_reward_does_not_increase_for_padding_progress_or_answer() -> None:
    tool_state = _state()
    final_state = _state(expected_mode="final", expected_tools=[])
    policy = RouterRewardPolicy()
    tool = teacher_preferred_output(tool_state)
    final = teacher_preferred_output(final_state)
    padded_tool = {**tool, "progress": tool["progress"] + "，正在继续处理" * 20}
    padded_final = {**final, "answer": final["answer"] + "。补充说明" * 20}

    assert policy.score(tool, tool_state).policy_reward == policy.score(
        padded_tool, tool_state
    ).policy_reward
    assert policy.score(final, final_state).policy_reward == policy.score(
        padded_final, final_state
    ).policy_reward


def test_environment_advances_successful_episode_and_assigns_terminal_bonus() -> None:
    first = _state(max_steps=2, next_state_id="episode-1-s1", terminal=False)
    second = _state(
        state_id="episode-1-s1",
        step_index=1,
        max_steps=2,
        expected_mode="final",
        next_state_id=None,
        terminal=True,
    )
    environment = RouterRLEnvironment([first, second])

    reset = environment.reset("episode-1")
    first_step = environment.step(teacher_preferred_output(first))
    second_step = environment.step(teacher_preferred_output(second))

    assert reset.state_id == first.state_id
    assert first_step.success_transition is True
    assert first_step.next_state_id == second.state_id
    assert second_step.terminated is True
    assert second_step.episode_return > first_step.episode_return


def test_environment_terminates_on_wrong_semantic_action() -> None:
    state = _state(max_steps=2, next_state_id="episode-1-s1", terminal=False)
    successor = _state(state_id="episode-1-s1", step_index=1, max_steps=2, expected_mode="final")
    environment = RouterRLEnvironment([state, successor])
    environment.reset("episode-1")

    result = environment.step(teacher_rejected_output(state))

    assert result.terminated is True
    assert result.success_transition is False
    assert result.next_state_id is None


def test_group_relative_advantages_are_centered() -> None:
    advantages = group_relative_advantages([0.1, 0.3, 0.6, 1.0])

    assert sum(advantages) == pytest.approx(0.0, abs=1e-5)
    assert advantages[-1] > advantages[0]
    assert group_relative_advantages([0.5, 0.5]) == [0.0, 0.0]


def test_audit_rejects_material_split_leak() -> None:
    train = _state(material_ids=[18])
    validation = _state(
        state_id="episode-v-s0",
        episode_id="episode-v",
        split="validation",
        material_ids=[18],
    )

    audit = audit_states([train, validation])

    assert audit["passed"] is False
    assert audit["material_split_leaks"] == {"18": ["train", "validation"]}


def test_spec_rejects_diagnostic_or_holdout_provenance() -> None:
    state = _state()
    mapping = {
        "schema_version": "studyhub.agent.router_rl.state.v1",
        "state_id": state.state_id,
        "episode_id": state.episode_id,
        "split": state.split,
        "family": state.family,
        "step_index": state.step_index,
        "max_steps": state.max_steps,
        "request_payload": state.request_payload,
        "messages": list(state.messages),
        "reward_rubric": {
            "expected_mode": state.rubric.expected_mode,
            "expected_tools": list(state.rubric.expected_tools),
        },
        "source_material_ids": list(state.source_material_ids),
        "next_state_id": None,
        "terminal": True,
        "training_eligible": True,
        "training_export_allowed": True,
        "isolation": {
            "production_api_called": False,
            "production_database_accessed": False,
            "paid_material_used": False,
            "final_holdout_read": False,
        },
        "provenance": {"source": "router_teacher_hidden_v1"},
    }

    with pytest.raises(RouterRLSpecError, match="forbidden source"):
        RouterRLState.from_mapping(mapping)


def test_evaluation_summary_requires_complete_consistent_predictions() -> None:
    state = _state(split="validation")
    ledger = score_double_ledger(teacher_preferred_output(state), state).to_dict()
    row = {
        "state_id": state.state_id,
        "episode_id": state.episode_id,
        "family": state.family,
        "sample_index": 0,
        "completion_tokens": 20,
        "hit_decode_limit": False,
        "double_ledger": ledger,
    }

    summary = summarize_rows([row], states=[state])

    assert summary["states"] == 1
    assert summary["raw"]["choice_success_rate"] == 1.0
    assert summary["raw"]["episode_success_rate"] == 1.0
    with pytest.raises(ValueError, match="unknown states"):
        summarize_rows([{**row, "state_id": "unknown"}], states=[state])
    with pytest.raises(ValueError, match="duplicate state/sample"):
        summarize_rows([row, row], states=[state])


def _evaluation_summary(*, reward: float = 0.8, choice: float = 0.8, episode: float = 0.6) -> dict:
    return {
        "split": "validation",
        "dataset_sha256": "dataset",
        "adapter_sha256": "baseline",
        "decoding": {"do_sample": False},
        "states": 10,
        "predictions": 10,
        "decode_limit_hits": 0,
        "constraint_dependency_delta_mean": -0.05,
        "constraint": {"corrections": {"canonicalize_contract": 2}},
        "isolation": {
            "production_api_called": False,
            "production_database_accessed": False,
            "final_holdout_read": False,
        },
        "raw": {
            "policy_reward_mean": reward,
            "choice_success_rate": choice,
            "episode_success_rate": episode,
            "hard_gates": {"strict_json": 1.0, "permission_safe": 1.0},
            "families": {
                "initial_search": {"choice_success_rate": choice, "reward_mean": reward, "samples": 10}
            },
            "reward_hacking_flags": {"premature_final": 1},
        },
        "executable": {
            "policy_reward_mean": reward - 0.05,
            "choice_success_rate": choice,
            "hard_gates": {"strict_json": 1.0, "permission_safe": 1.0},
        },
    }


def test_candidate_gate_uses_raw_non_regression_and_rejects_safety_drop() -> None:
    baseline = _evaluation_summary()
    improved = _evaluation_summary(reward=0.82, choice=0.9, episode=0.7)
    improved["adapter_sha256"] = "candidate"

    passed = assess_candidate(baseline=baseline, candidate=improved)
    unsafe = json.loads(json.dumps(improved))
    unsafe["raw"]["hard_gates"]["strict_json"] = 0.9
    failed = assess_candidate(baseline=baseline, candidate=unsafe)

    assert passed["passed"] is True
    assert failed["passed"] is False
    assert "raw_hard_gates_non_regression" in failed["blockers"]


def test_training_gate_requires_raw_ledger_and_isolation() -> None:
    summary = {
        "training_succeeded": True,
        "rollouts": 48,
        "stability": {
            "mean_kl": 0.001,
            "max_kl": 0.002,
            "mean_clip_fraction": 0.1,
            "mean_entropy_proxy": 0.2,
            "mean_completion_tokens": 100,
        },
        "reward": {"mean": 0.7},
        "gpu": {"peak_memory_mib": 60_000},
        "objective": {
            "reward_ledger_used_for_gradient": "raw_policy_proposal",
            "executable_ledger_used_for_gradient": False,
            "deterministic_constraints_rewarded": False,
            "group_relative_advantage": True,
            "reference_kl_beta": 0.02,
        },
        "isolation": {"production_api_called": False, "production_database_accessed": False},
    }

    result = assess_training_run(summary, expected_rollouts=48)

    assert result["passed"] is True
    summary["objective"]["executable_ledger_used_for_gradient"] = True
    assert assess_training_run(summary, expected_rollouts=48)["passed"] is False


def test_constraint_gap_diagnostic_marks_legacy_test_as_consumed(tmp_path) -> None:
    state = _state(split="test")
    states_path = tmp_path / "states.jsonl"
    state_mapping = {
        "schema_version": "studyhub.agent.router_rl.state.v1",
        "state_id": state.state_id,
        "episode_id": state.episode_id,
        "split": state.split,
        "family": state.family,
        "step_index": state.step_index,
        "max_steps": state.max_steps,
        "request_payload": state.request_payload,
        "messages": list(state.messages),
        "reward_rubric": {
            "expected_mode": state.rubric.expected_mode,
            "expected_tools": list(state.rubric.expected_tools),
            "query_terms": list(state.rubric.query_terms),
            "trusted_material_ids": list(state.rubric.trusted_material_ids),
            "explicit_pages": list(state.rubric.explicit_pages),
        },
        "source_material_ids": list(state.source_material_ids),
        "next_state_id": state.next_state_id,
        "terminal": state.terminal,
        "training_eligible": False,
        "training_export_allowed": False,
        "isolation": {
            "production_api_called": False,
            "production_database_accessed": False,
            "paid_material_used": False,
            "final_holdout_read": False,
        },
        "provenance": {"source": "frozen_free_public_backup"},
    }
    states_path.write_text(json.dumps(state_mapping, ensure_ascii=False) + "\n", encoding="utf-8")
    prediction_path = tmp_path / "predictions.jsonl"
    prediction_path.write_text(
        json.dumps(
            {
                "state_id": state.state_id,
                "raw_generated": json.dumps(teacher_preferred_output(state), ensure_ascii=False),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = diagnose(
        states_path=states_path,
        predictions={"baseline": prediction_path, "candidate": prediction_path},
    )

    assert result["legacy_test_consumed"] is True
    assert result["allowed_for_v2_training_selection_or_gate"] is False
    assert result["comparison"]["candidate_minus_baseline_absolute_gap"] == 0.0
