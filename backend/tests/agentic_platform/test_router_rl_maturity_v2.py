from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ml.agentic_platform.rl.maturity_v2 import train_grpo as train_grpo_module
from ml.agentic_platform.rl.maturity_v2.train_grpo import (
    _audit_schedule,
    _build_schedule,
    _scheduled_learning_rate,
)
from ml.agentic_platform.rl.maturity_v2.actions import build_action_space, decision_messages
from ml.agentic_platform.rl.maturity_v2.build_dataset import CRITICAL_BOUNDARY_FAMILIES
from ml.agentic_platform.rl.maturity_v2.gate import (
    assess_formal_training_run,
    assess_locked_split,
    assess_multi_seed,
    assess_validation_candidate,
    freeze_candidate,
    paired_bootstrap,
)
from ml.agentic_platform.rl.maturity_v2.formal_config import build_formal_config
from ml.agentic_platform.rl.maturity_v2.double_ledger_audit import (
    build_double_ledger_fix_audit,
)
from ml.agentic_platform.rl.maturity_v2.formal_gate import (
    _assess_run_lock,
    freeze_selected_candidate,
)
from ml.agentic_platform.rl.maturity_v2.locked_gate import (
    assert_locked_evaluation_allowed,
)
from ml.agentic_platform.rl.maturity_v2.offline_package import (
    _verify_base_export,
    inspect_production_defaults,
)
from ml.agentic_platform.rl.maturity_v2.robustness import _summarize, _transforms
from ml.agentic_platform.rl.maturity_v2.spec import (
    MATURITY_SCHEMA_VERSION,
    MaturityDatasetError,
    MaturityRouterState,
    audit_maturity_states,
    load_maturity_states,
)
from ml.agentic_platform.rl.maturity_v2.trajectory import (
    TrajectoryRollout,
    TrajectoryStep,
    credit_trajectories,
)
from ml.agentic_platform.rl.reward import RouterRewardPolicy, score_double_ledger
from ml.agentic_platform.rl.spec import canonical_json, sha256_file


def _state_mapping(
    *,
    state_id: str,
    episode_id: str,
    split: str,
    step_index: int = 0,
    max_steps: int = 1,
    next_state_id: str | None = None,
    terminal: bool = True,
    material_ids: list[int] | None = None,
    template_id: str | None = None,
) -> dict:
    material_ids = material_ids or []
    payload = {
        "current_user_query": f"{split}：检索通信原理免费资料 {state_id}",
        "force_final": False,
        "budget": {
            "remaining_rounds": 2,
            "remaining_tool_calls": 3,
            "remaining_search_calls": 1,
            "remaining_candidate_slots": 8,
        },
        "task_context": {"course_terms": ["通信原理"]},
        "tool_observations": [],
        "search_history": [],
    }
    return {
        "schema_version": MATURITY_SCHEMA_VERSION,
        "state_id": state_id,
        "episode_id": episode_id,
        "split": split,
        "template_id": template_id or f"{split}/template/{state_id}",
        "family": "initial_search",
        "step_index": step_index,
        "max_steps": max_steps,
        "request_payload": payload,
        "messages": [
            {"role": "system", "content": "只读 Router"},
            {"role": "user", "content": canonical_json(payload)},
        ],
        "reward_rubric": {
            "expected_mode": "tools",
            "expected_tools": ["search_materials"],
            "query_terms": ["通信原理"],
            "trusted_material_ids": material_ids,
        },
        "oracle_output": {
            "mode": "tools",
            "progress": "检索中",
            "task_context": {"course_terms": ["通信原理"]},
            "actions": [{"name": "search_materials", "arguments": {"query": "通信原理", "limit": 6}}],
        },
        "source_material_ids": material_ids,
        "next_state_id": next_state_id,
        "terminal": terminal,
        "training_eligible": split == "train",
        "training_export_allowed": split == "train",
        "isolation": {
            "production_api_called": False,
            "production_database_accessed": False,
            "production_oss_write_called": False,
            "paid_material_used": False,
            "legacy_v1_test_used": False,
            "production_final_holdout_read": False,
        },
        "provenance": {"source": "frozen_free_public_backup_v2"},
    }


def test_maturity_spec_accepts_train_and_locks_sealed(tmp_path) -> None:
    train = _state_mapping(state_id="train-s0", episode_id="train-e0", split="train")
    sealed = _state_mapping(state_id="sealed-s0", episode_id="sealed-e0", split="sealed")
    path = tmp_path / "states.jsonl"
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in (train, sealed)),
        encoding="utf-8",
    )

    assert MaturityRouterState.from_mapping(train).training_export_allowed is True
    assert len(load_maturity_states(path, splits={"train"})) == 1
    with pytest.raises(MaturityDatasetError, match="sealed split is locked"):
        load_maturity_states(path, splits={"sealed"})
    assert len(load_maturity_states(path, splits={"sealed"}, allow_sealed=True)) == 1


def test_maturity_spec_rejects_eval_training_export() -> None:
    value = _state_mapping(state_id="validation-s0", episode_id="validation-e0", split="validation")
    value["training_eligible"] = True
    value["training_export_allowed"] = True

    with pytest.raises(MaturityDatasetError, match="only eligible train states"):
        MaturityRouterState.from_mapping(value)


def test_maturity_audit_detects_material_template_and_query_leaks() -> None:
    train = MaturityRouterState.from_mapping(
        _state_mapping(
            state_id="train-s0",
            episode_id="train-e0",
            split="train",
            material_ids=[18],
            template_id="shared-template",
        )
    )
    validation_mapping = _state_mapping(
        state_id="validation-s0",
        episode_id="validation-e0",
        split="validation",
        material_ids=[18],
        template_id="shared-template",
    )
    validation_mapping["request_payload"]["current_user_query"] = train.request_payload["current_user_query"]
    validation_mapping["messages"][1]["content"] = canonical_json(validation_mapping["request_payload"])
    validation = MaturityRouterState.from_mapping(validation_mapping)

    audit = audit_maturity_states([train, validation])

    assert audit["passed"] is False
    assert audit["leaks"]["material"]
    assert audit["leaks"]["episode_template"]
    assert audit["leaks"]["normalized_query"]


def test_maturity_audit_validates_episode_graph() -> None:
    first = _state_mapping(
        state_id="train-s0",
        episode_id="train-e0",
        split="train",
        step_index=0,
        max_steps=2,
        next_state_id="train-s1",
        terminal=False,
    )
    second = _state_mapping(
        state_id="train-s1",
        episode_id="train-e0",
        split="train",
        step_index=1,
        max_steps=2,
    )

    audit = audit_maturity_states([MaturityRouterState.from_mapping(first), MaturityRouterState.from_mapping(second)])

    assert audit["passed"] is True
    assert audit["episodes"] == 1


def test_maturity_protocol_defines_ten_critical_boundary_families() -> None:
    assert len(CRITICAL_BOUNDARY_FAMILIES) == 10
    assert "permission_boundary" in CRITICAL_BOUNDARY_FAMILIES
    assert "untrusted_observation" in CRITICAL_BOUNDARY_FAMILIES
    assert "candidate_before_read" in CRITICAL_BOUNDARY_FAMILIES


def test_formal_config_is_frozen_from_validation_only_sweeps(
    tmp_path,
    monkeypatch,
) -> None:
    primary_path = tmp_path / "primary.json"
    scale_path = tmp_path / "scale.json"
    stability_path = tmp_path / "stability.json"
    output_path = tmp_path / "formal.json"
    primary_path.write_text(
        json.dumps(
            {
                "selected_trial": "rank16_base",
                "selected_config": {"lora_rank": 16},
                "required_lora_ranks_compared": True,
                "required_hyperparameter_axes_compared": True,
                "test_read": False,
                "sealed_read": False,
                "production_access": False,
            }
        ),
        encoding="utf-8",
    )
    scale_path.write_text(
        json.dumps(
            {
                "best_screen_trial": "group20_entropy0",
                "gate_passed": False,
                "selected_trial": None,
                "selected_config": None,
                "required_group_scale_compared": True,
                "required_entropy_scale_compared": True,
                "test_read": False,
                "sealed_read": False,
                "production_access": False,
            }
        ),
        encoding="utf-8",
    )
    selected_config = {
                    "lora_rank": 16,
                    "learning_rate": 1e-5,
                    "learning_rate_schedule": "cosine",
                    "learning_rate_decay_optimizer_updates": 80,
                    "learning_rate_min_ratio": 0.02,
                    "reference_kl_beta": 0.02,
                    "trajectory_discount": 0.95,
                    "group_size": 10,
                    "material_episodes_per_update": 1,
                    "boundary_episodes_per_update": 2,
                    "entropy_beta": 0.002,
                    "action_temperature": 1.25,
    }
    stability_path.write_text(
        json.dumps(
            {
                "gate_passed": True,
                "selected_trial": "cosine_decay80",
                "selected_config": selected_config,
                "trials": [
                    {
                        "name": "cosine_decay80",
                        "formal_eligible": True,
                        "config": selected_config,
                        "training": {"optimizer_updates": 120},
                        "validation_gate": {"passed": True},
                    }
                ],
                "required_mixture_control_compared": True,
                "required_decay_horizons_compared": True,
                "required_schedule_shapes_compared": True,
                "test_read": False,
                "sealed_read": False,
                "production_access": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "ml.agentic_platform.rl.maturity_v2.formal_config.GRPOConfig.load",
        lambda _path: SimpleNamespace(planned_trajectory_rollouts=10_000),
    )

    config = build_formal_config(
        primary_results_path=primary_path,
        failed_scale_results_path=scale_path,
        stability_results_path=stability_path,
        output_path=output_path,
    )

    assert config["rollout_updates"] == 500
    assert config["group_size"] == 10
    assert config["formal_run"] is True
    assert config["checkpoint_every"] == 100
    assert config["boundary_episodes_per_update"] == 2
    assert config["learning_rate_schedule"] == "cosine"
    assert config["learning_rate_decay_optimizer_updates"] == 667
    assert config["formal_protocol"]["minimum_trajectory_rollouts_per_seed"] == 10_000
    assert config["selection_evidence"]["failed_scale_gate_passed"] is False
    assert config["selection_evidence"]["test_read"] is False


def test_constrained_action_space_keeps_raw_candidates_inside_hard_gates() -> None:
    state = MaturityRouterState.from_mapping(_state_mapping(state_id="train-s0", episode_id="train-e0", split="train"))
    space = build_action_space(state)
    policy = RouterRewardPolicy()

    assert space.oracle_route in space.routes
    assert len(space.codes) == len(set(space.codes))
    assert all(all(policy.score(candidate.output, state).hard_gates.values()) for candidate in space.candidates)
    messages = decision_messages(state, space)
    assert messages[1]["content"].endswith("动作代码：")
    assert "只输出一个代码字符" in messages[1]["content"]


def test_trajectory_credit_propagates_terminal_outcome_to_earlier_steps() -> None:
    successful = TrajectoryRollout(
        episode_id="episode",
        rollout_index=0,
        completed=True,
        steps=(
            TrajectoryStep("s0", 0, "0", 0.8, True),
            TrajectoryStep("s1", 1, "1", 0.8, True),
        ),
    )
    failed = TrajectoryRollout(
        episode_id="episode",
        rollout_index=1,
        completed=False,
        steps=(
            TrajectoryStep("s0", 0, "0", 0.8, True),
            TrajectoryStep("s1", 1, "5", 0.2, False),
        ),
    )

    credited = credit_trajectories(
        [successful, failed],
        discount=0.95,
        terminal_bonus=0.4,
        failure_penalty=0.4,
    )
    first = [item for item in credited if item.state_id == "s0"]

    assert first[0].return_to_go > first[1].return_to_go
    assert first[0].advantage > 0
    assert first[1].advantage < 0


def test_boundary_schedule_is_stratified_and_seed_deterministic() -> None:
    material_first = _state_mapping(
        state_id="train-material-s0",
        episode_id="train-material",
        split="train",
        step_index=0,
        max_steps=2,
        next_state_id="train-material-s1",
        terminal=False,
    )
    material_second = _state_mapping(
        state_id="train-material-s1",
        episode_id="train-material",
        split="train",
        step_index=1,
        max_steps=2,
    )
    episodes = {
        "train-material": [
            MaturityRouterState.from_mapping(material_first),
            MaturityRouterState.from_mapping(material_second),
        ]
    }
    for index, family in enumerate(CRITICAL_BOUNDARY_FAMILIES):
        mapping = _state_mapping(
            state_id=f"train-boundary-{index}",
            episode_id=f"train-boundary-{index}",
            split="train",
        )
        mapping["family"] = family
        episodes[mapping["episode_id"]] = [MaturityRouterState.from_mapping(mapping)]

    schedule = _build_schedule(
        episodes,
        updates=10,
        material_per_update=1,
        boundary_per_update=1,
        seed=41,
    )
    repeated = _build_schedule(
        episodes,
        updates=10,
        material_per_update=1,
        boundary_per_update=1,
        seed=41,
    )
    audit = _audit_schedule(episodes, schedule)

    assert schedule == repeated
    assert audit["boundary_family_counts"] == {family: 1 for family in sorted(CRITICAL_BOUNDARY_FAMILIES)}
    assert audit["boundary_family_max_min_gap"] == 0


def test_learning_rate_schedule_anneals_and_holds_floor() -> None:
    config = SimpleNamespace(
        learning_rate=1e-5,
        learning_rate_schedule="cosine",
        learning_rate_decay_optimizer_updates=40,
        learning_rate_min_ratio=0.02,
    )

    assert _scheduled_learning_rate(config, 0) == pytest.approx(1e-5)
    assert _scheduled_learning_rate(config, 20) < 1e-5
    assert _scheduled_learning_rate(config, 40) == pytest.approx(2e-7)
    assert _scheduled_learning_rate(config, 400) == pytest.approx(2e-7)


def _evaluation_summary(
    *,
    split: str = "validation",
    reward: float = 0.80,
    choice: float = 0.96,
    episode: float = 0.92,
    adapter_sha256: str = "candidate",
) -> dict:
    families = {
        family: {
            "samples": 30,
            "reward_mean": reward,
            "choice_success_rate": choice,
        }
        for family in CRITICAL_BOUNDARY_FAMILIES
    }
    return {
        "split": split,
        "states": 400,
        "episodes": 100,
        "dataset_sha256": f"{split}-dataset",
        "adapter_path": "/tmp/adapter",
        "adapter_sha256": adapter_sha256,
        "decoding": {
            "type": "constrained_single_token_argmax",
            "batch_size": 1,
            "action_temperature": 1.0,
            "max_prompt_tokens": 4096,
            "decode_limit_rate": 0.0,
        },
        "raw": {
            "policy_reward_mean": reward,
            "choice_success_rate": choice,
            "episode_success_rate": episode,
            "reward_hacking_rate": 0.0,
            "families": families,
            "hard_gates": {
                "strict_json": 1.0,
                "contract_valid": 1.0,
                "readonly_tool": 1.0,
                "budget_respected": 1.0,
                "trusted_references": 1.0,
                "explicit_pages_preserved": 1.0,
                "sensitive_output_absent": 1.0,
                "permission_safe": 1.0,
            },
        },
        "constraint": {"severity_mean": 0.0},
        "raw_executable": {"choice_success_gap_absolute": 0.0},
        "isolation": {
            "production_api_called": False,
            "production_database_accessed": False,
            "production_oss_write_called": False,
            "paid_material_used": False,
            "legacy_v1_test_used": False,
            "production_final_holdout_read": False,
        },
    }


def _bootstrap_result(delta: float = 0.04) -> dict:
    interval = {"mean": delta, "ci95_lower": 0.01, "ci95_upper": 0.07}
    return {
        "method": "paired_nonparametric_bootstrap",
        "resamples": 5_000,
        "seed": 26_081_201,
        "reward_delta": interval,
        "choice_success_delta": interval,
        "episode_success_delta": interval,
    }


def test_paired_bootstrap_uses_matching_state_and_episode_pairs(tmp_path) -> None:
    baseline_path = tmp_path / "baseline.jsonl"
    candidate_path = tmp_path / "candidate.jsonl"
    baseline_rows = [
        {
            "state_id": f"s{index}",
            "episode_id": f"e{index // 2}",
            "double_ledger": {
                "raw": {
                    "policy_reward": 0.5,
                    "components": {"tool_choice": 1.0, "stop_decision": 1.0},
                }
            },
        }
        for index in range(4)
    ]
    candidate_rows = json.loads(json.dumps(baseline_rows))
    for row in candidate_rows:
        row["double_ledger"]["raw"]["policy_reward"] = 0.7
    baseline_path.write_text(
        "".join(json.dumps(row) + "\n" for row in baseline_rows),
        encoding="utf-8",
    )
    candidate_path.write_text(
        "".join(json.dumps(row) + "\n" for row in candidate_rows),
        encoding="utf-8",
    )

    result = paired_bootstrap(baseline_path, candidate_path, samples=500, seed=7)

    assert result["reward_delta"] == {
        "mean": 0.2,
        "ci95_lower": 0.2,
        "ci95_upper": 0.2,
    }
    assert result["choice_success_delta"]["mean"] == 0.0


def test_validation_and_locked_gates_enforce_preregistered_raw_thresholds() -> None:
    baseline = _evaluation_summary(reward=0.75, choice=0.90, episode=0.80, adapter_sha256="sft")
    candidate = _evaluation_summary()

    validation = assess_validation_candidate(
        baseline=baseline,
        candidate=candidate,
        statistics_result=_bootstrap_result(),
    )
    assert validation["passed"] is True

    candidate["raw_executable"]["choice_success_gap_absolute"] = 0.03
    validation = assess_validation_candidate(
        baseline=baseline,
        candidate=candidate,
        statistics_result=_bootstrap_result(),
    )
    assert validation["passed"] is False
    assert "raw_executable_choice_gap" in validation["blockers"]

    locked_baseline = _evaluation_summary(
        split="test",
        reward=0.75,
        choice=0.90,
        episode=0.80,
        adapter_sha256="sft",
    )
    locked_candidate = _evaluation_summary(split="test")
    locked = assess_locked_split(
        baseline=locked_baseline,
        candidate=locked_candidate,
        statistics_result=_bootstrap_result(),
        split="test",
    )
    assert locked["passed"] is True


def test_multi_seed_gate_requires_five_independent_stable_candidates() -> None:
    assessments = [{"passed": True} for _ in range(5)]
    summaries = [
        _evaluation_summary(
            choice=0.96 + index * 0.001,
            episode=0.92 + index * 0.001,
            adapter_sha256=f"seed-{index}",
        )
        for index in range(5)
    ]

    result = assess_multi_seed(assessments, summaries)

    assert result["passed"] is True
    summaries[-1]["adapter_sha256"] = summaries[0]["adapter_sha256"]
    result = assess_multi_seed(assessments, summaries)
    assert result["passed"] is False
    assert "five_independent_seeds" in result["blockers"]


def test_candidate_freeze_refuses_failed_gate_and_is_immutable(tmp_path) -> None:
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    training_path = tmp_path / "training.json"
    config_path = tmp_path / "config.json"
    acceptance_path = tmp_path / "acceptance.json"
    candidate = _evaluation_summary()
    training = {"algorithm": "trajectory_constrained_token_grpo_v2", "seed": 7}
    for path, value in (
        (baseline_path, _evaluation_summary(adapter_sha256="sft")),
        (candidate_path, candidate),
        (training_path, training),
        (config_path, {"formal_run": True}),
        (acceptance_path, {"scope": "offline"}),
    ):
        path.write_text(json.dumps(value), encoding="utf-8")
    output_path = tmp_path / "frozen.json"

    with pytest.raises(ValueError, match="failed Validation"):
        freeze_candidate(
            output_path=output_path,
            baseline_summary_path=baseline_path,
            candidate_summary_path=candidate_path,
            training_summary_path=training_path,
            config_path=config_path,
            acceptance_path=acceptance_path,
            assessment={"passed": False},
            multi_seed={"passed": True},
        )

    freeze_candidate(
        output_path=output_path,
        baseline_summary_path=baseline_path,
        candidate_summary_path=candidate_path,
        training_summary_path=training_path,
        config_path=config_path,
        acceptance_path=acceptance_path,
        assessment={"passed": True},
        multi_seed={"passed": True},
    )
    assert json.loads(output_path.read_text())["status"] == "frozen_before_test"
    with pytest.raises(FileExistsError, match="already frozen"):
        freeze_candidate(
            output_path=output_path,
            baseline_summary_path=baseline_path,
            candidate_summary_path=candidate_path,
            training_summary_path=training_path,
            config_path=config_path,
            acceptance_path=acceptance_path,
            assessment={"passed": True},
            multi_seed={"passed": True},
        )


def test_formal_training_gate_requires_complete_resumed_trajectory_run(tmp_path) -> None:
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    weights = adapter / "adapter_model.safetensors"
    weights.write_bytes(b"offline-adapter")
    metrics = tmp_path / "trainer_metrics.jsonl"
    metrics.write_text(
        "".join(
            json.dumps(
                {
                    "rollout_update": update,
                    "optimizer_steps": update * 2,
                    "trajectory_rollouts": 20,
                    "raw_reward_mean": 0.8,
                    "return_to_go_mean": 1.2,
                    "post_update_policy_ratio_mean": 1.0,
                    "post_update_policy_ratio_std": 0.01,
                    "post_update_clip_fraction": 0.1,
                    "reference_kl": 0.1,
                    "true_token_entropy_mean": 0.2,
                    "prompt_tokens_mean": 1000,
                    "cuda_memory_peak_mib": 1000,
                    "learning_rate": 2e-7,
                    "policy_epochs": [
                        {"grad_norm": 0.5, "learning_rate": 2e-7},
                        {"grad_norm": 0.4, "learning_rate": 2e-7},
                    ],
                }
            )
            + "\n"
            for update in range(1, 501)
        ),
        encoding="utf-8",
    )
    trajectories = tmp_path / "trajectory_rollouts.jsonl"
    trajectories.write_text(
        '{"steps":[{"state_id":"s0"}]}\n' * 10_000,
        encoding="utf-8",
    )
    invocations = tmp_path / "invocation_history.jsonl"
    invocations.write_text(
        "\n".join(
            json.dumps(value)
            for value in (
                {
                    "start_rollout_update": 1,
                    "end_rollout_update": 100,
                    "resumed": False,
                    "completed_formal_target": False,
                },
                {
                    "start_rollout_update": 101,
                    "end_rollout_update": 500,
                    "resumed": True,
                    "completed_formal_target": True,
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )
    schedule = tmp_path / "episode_schedule.json"
    schedule.write_text('{"audit":{"stratified_boundary_rotation":true}}\n')
    summary = {
        "formal_run": True,
        "training_succeeded": True,
        "seed": 3407,
        "rollout_updates": 500,
        "optimizer_updates": 1_000,
        "trajectory_rollouts": 10_000,
        "trajectory_rollouts_per_second_total": 1.0,
        "minimum_trajectory_rollouts_satisfied": True,
        "minimum_optimizer_updates_satisfied": True,
        "checkpoint_resume_exercised": True,
        "stability": {
            "finite": True,
            "true_token_entropy_observed": True,
            "post_update_policy_ratio_observed": True,
            "clip_fraction_measured": True,
            "trajectory_credit_signal_observed": True,
            "learning_rate_decay_observed": True,
        },
        "optimization": {
            "learning_rate": 1e-5,
            "learning_rate_schedule": "cosine",
            "final_learning_rate": 2e-7,
        },
        "schedule_audit": {
            "stratified_boundary_rotation": True,
            "boundary_family_counts": {family: 100 for family in CRITICAL_BOUNDARY_FAMILIES},
            "boundary_family_max_min_gap": 0,
        },
        "raw_hard_gate_failures": {},
        "objective": {
            "trajectory_return_to_go": True,
            "group_relative_advantage": True,
            "clipped_post_update_policy_ratio": True,
            "frozen_reference_kl": True,
            "true_token_entropy": True,
            "raw_policy_reward_only": True,
            "executable_ledger_used_for_gradient": False,
            "deterministic_constraints_rewarded": False,
        },
        "artifacts": {
            "adapter_path": str(adapter),
            "adapter_sha256": sha256_file(weights),
            "metrics_sha256": sha256_file(metrics),
            "trajectories_path": str(trajectories),
            "trajectories_sha256": sha256_file(trajectories),
            "invocation_history_path": str(invocations),
            "invocation_history_sha256": sha256_file(invocations),
            "episode_schedule_path": str(schedule),
            "episode_schedule_sha256": sha256_file(schedule),
        },
        "lora": {"trainable_parameters": 1024},
        "gpu": {"peak_memory_mib": 1000},
        "isolation": {
            "production_api_called": False,
            "production_database_accessed": False,
            "production_oss_write_called": False,
            "paid_material_used": False,
            "test_read": False,
            "sealed_read": False,
            "production_final_holdout_read": False,
        },
    }

    result = assess_formal_training_run(
        summary=summary,
        metrics_path=metrics,
        expected_seed=3407,
    )

    assert result["passed"] is True
    summary["checkpoint_resume_exercised"] = False
    result = assess_formal_training_run(
        summary=summary,
        metrics_path=metrics,
        expected_seed=3407,
    )
    assert result["passed"] is False
    assert result["blockers"] == ["checkpoint_resume"]


def test_formal_run_lock_cross_checks_config_data_and_implementation(tmp_path) -> None:
    train = tmp_path / "train.jsonl"
    reference = tmp_path / "reference.jsonl"
    config = tmp_path / "formal.json"
    snapshot = tmp_path / "config.snapshot.json"
    summary = tmp_path / "run_summary.json"
    metrics = tmp_path / "trainer_metrics.jsonl"
    manifest = tmp_path / "run_manifest.json"
    schedule = tmp_path / "episode_schedule.json"
    train.write_text("{}\n", encoding="utf-8")
    reference.write_text("{}\n", encoding="utf-8")
    config_value = {
        "train_path": str(train),
        "reference_cache_path": str(reference),
    }
    serialized_config = json.dumps(config_value, indent=2, sort_keys=True) + "\n"
    config.write_text(serialized_config, encoding="utf-8")
    snapshot.write_text(serialized_config, encoding="utf-8")
    metrics.write_text('{"rollout_update":1}\n', encoding="utf-8")
    schedule.write_text('{"updates":[]}\n', encoding="utf-8")
    summary.write_text(
        json.dumps(
            {
                "artifacts": {
                    "metrics_sha256": sha256_file(metrics),
                    "episode_schedule_path": str(schedule),
                    "episode_schedule_sha256": sha256_file(schedule),
                }
            }
        ),
        encoding="utf-8",
    )
    train_grpo_path = Path(train_grpo_module.__file__)
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "studyhub.agent.router_rl.training_manifest.v2",
                "config_sha256": sha256_file(config),
                "summary_sha256": sha256_file(summary),
                "train_sha256": sha256_file(train),
                "reference_cache_sha256": sha256_file(reference),
                "implementation_sha256": sha256_file(Path(train_grpo_path)),
                "episode_schedule_sha256": sha256_file(schedule),
                "production_access": False,
                "test_read": False,
                "sealed_read": False,
            }
        ),
        encoding="utf-8",
    )

    result = _assess_run_lock(
        run_manifest_path=manifest,
        config_snapshot_path=snapshot,
        training_summary_path=summary,
        metrics_path=metrics,
        config_path=config,
        formal_config=config_value,
    )

    assert result["passed"] is True
    snapshot.write_text("{}\n", encoding="utf-8")
    assert (
        _assess_run_lock(
            run_manifest_path=manifest,
            config_snapshot_path=snapshot,
            training_summary_path=summary,
            metrics_path=metrics,
            config_path=config,
            formal_config=config_value,
        )["passed"]
        is False
    )


def test_formal_freeze_rejects_changed_config_before_reading_candidate(tmp_path) -> None:
    gate_path = tmp_path / "gate.json"
    config_path = tmp_path / "formal.json"
    acceptance_path = tmp_path / "acceptance.json"
    robustness_path = tmp_path / "robustness.json"
    config_path.write_text('{"version":1}\n', encoding="utf-8")
    acceptance_path.write_text('{"version":1}\n', encoding="utf-8")
    gate_path.write_text(
        json.dumps(
            {
                "passed": True,
                "status": "validation_selected_pending_robustness",
                "formal_config_sha256": sha256_file(config_path),
                "acceptance_sha256": sha256_file(acceptance_path),
                "selected_seed": 3407,
                "seeds": [{"seed": 3407}],
            }
        ),
        encoding="utf-8",
    )
    robustness_path.write_text('{"passed":true}\n', encoding="utf-8")
    config_path.write_text('{"version":2}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="formal config changed"):
        freeze_selected_candidate(
            gate_path=gate_path,
            baseline_dir=tmp_path / "baseline",
            training_root=tmp_path / "training",
            evaluation_root=tmp_path / "evaluation",
            robustness_summary_path=robustness_path,
            config_path=config_path,
            acceptance_path=acceptance_path,
            output_path=tmp_path / "frozen.json",
        )


def test_locked_split_authorization_is_one_shot_and_sequential(tmp_path) -> None:
    acceptance = tmp_path / "acceptance.json"
    acceptance.write_text('{"scope":"offline"}', encoding="utf-8")
    frozen_path = tmp_path / "frozen.json"
    frozen = {
        "status": "frozen_before_test",
        "test_read": False,
        "sealed_read": False,
        "acceptance_sha256": sha256_file(acceptance),
    }
    frozen_path.write_text(json.dumps(frozen), encoding="utf-8")
    test_marker = tmp_path / "test_access.json"

    assert_locked_evaluation_allowed(
        split="test",
        frozen_manifest=frozen,
        frozen_manifest_path=frozen_path,
        acceptance_path=acceptance,
        access_marker_path=test_marker,
    )
    test_marker.write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError, match="already been consumed"):
        assert_locked_evaluation_allowed(
            split="test",
            frozen_manifest=frozen,
            frozen_manifest_path=frozen_path,
            acceptance_path=acceptance,
            access_marker_path=test_marker,
        )

    sealed_marker = tmp_path / "sealed_access.json"
    test_gate = tmp_path / "test_gate.json"
    with pytest.raises(ValueError, match="completed Test Gate"):
        assert_locked_evaluation_allowed(
            split="sealed",
            frozen_manifest=frozen,
            frozen_manifest_path=frozen_path,
            acceptance_path=acceptance,
            access_marker_path=sealed_marker,
            prior_test_gate_path=test_gate,
        )
    test_gate.write_text(
        json.dumps(
            {
                "split": "test",
                "passed": True,
                "candidate_manifest_sha256": sha256_file(frozen_path),
            }
        ),
        encoding="utf-8",
    )
    assert_locked_evaluation_allowed(
        split="sealed",
        frozen_manifest=frozen,
        frozen_manifest_path=frozen_path,
        acceptance_path=acceptance,
        access_marker_path=sealed_marker,
        prior_test_gate_path=test_gate,
    )


def test_robustness_perturbations_preserve_state_labels_and_gate_metrics() -> None:
    state = MaturityRouterState.from_mapping(_state_mapping(state_id="validation-s0", episode_id="validation-e0", split="validation"))
    for name, transform in _transforms().items():
        perturbed = transform(state)
        assert perturbed.state_id.endswith(
            {
                "query_politeness": "/polite",
                "irrelevant_display_field": "/display",
                "observation_order": "/observation-order",
                "untrusted_instruction_injection": "/injection",
            }[name]
        )
        assert perturbed.rubric == state.rubric
        assert build_action_space(perturbed).oracle_route == build_action_space(state).oracle_route
        ledger = score_double_ledger(state.oracle_output, perturbed)
        assert ledger.raw.components["tool_choice"] == 1.0
        assert ledger.executable.components["tool_choice"] == 1.0
        assert ledger.raw.components["stop_decision"] == 1.0
        assert ledger.executable.components["stop_decision"] == 1.0
        assert all(ledger.raw.hard_gates.values())

    rows = []
    for perturbation in _transforms():
        rows.append(
            {
                "family": "initial_search",
                "perturbation": perturbation,
                "route_success": True,
                "route_invariant": True,
                "raw_choice_success": True,
                "executable_choice_success": True,
                "raw_hard_gates": RouterRewardPolicy()
                .score(
                    state.oracle_output,
                    state,
                )
                .hard_gates,
                "reward_hacking_flags": [],
                "constraint_corrections": [],
            }
        )
    summary = _summarize(rows)
    assert summary["passed"] is True
    assert summary["route_invariance_rate"] == 1.0


def test_double_ledger_fix_audit_requires_reproduced_failure_and_zero_post_gap(
    tmp_path,
) -> None:
    hard_gates = {name: 1.0 for name in ("strict_json", "contract_valid")}
    isolation = {"production_access": False, "test_read": False, "sealed_read": False}
    common = {
        "adapter_sha256": "adapter",
        "dataset_sha256": "dataset",
        "base_states": 1,
        "perturbed_cases": 1,
        "route_success_rate": 1.0,
        "route_invariance_rate": 1.0,
        "reward_hacking_rate": 0.0,
        "raw_hard_gates": hard_gates,
        "isolation": isolation,
    }
    before_summary = tmp_path / "before-summary.json"
    after_summary = tmp_path / "after-summary.json"
    before_predictions = tmp_path / "before.jsonl"
    after_predictions = tmp_path / "after.jsonl"
    implementation = tmp_path / "implementation.py"
    before_summary.write_text(
        json.dumps(
            {
                **common,
                "passed": False,
                "blockers": ["raw_executable_choice_gap"],
                "raw_executable_choice_gap": 1.0,
            }
        )
    )
    after_summary.write_text(
        json.dumps(
            {
                **common,
                "passed": True,
                "blockers": [],
                "raw_executable_choice_gap": 0.0,
            }
        )
    )
    before_predictions.write_text(
        json.dumps(
            {
                "raw_choice_success": True,
                "executable_choice_success": False,
                "perturbation": "untrusted_instruction_injection",
                "constraint_corrections": ["safe_untrusted_continuation"],
            }
        )
        + "\n"
    )
    after_predictions.write_text(
        json.dumps(
            {
                "raw_choice_success": True,
                "executable_choice_success": True,
                "perturbation": "untrusted_instruction_injection",
                "constraint_corrections": ["ignore_untrusted_observation"],
            }
        )
        + "\n"
    )
    implementation.write_text("# locked implementation\n")

    result = build_double_ledger_fix_audit(
        before_summary_path=before_summary,
        before_predictions_path=before_predictions,
        after_summary_path=after_summary,
        after_predictions_path=after_predictions,
        implementation_paths=(implementation,),
        output_path=tmp_path / "audit.json",
    )

    assert result["passed"] is True
    assert result["before"]["choice_divergence_cases"] == 1
    assert result["after"]["choice_divergence_cases"] == 0


def test_offline_package_checks_disabled_defaults_and_base_hashes(tmp_path) -> None:
    root = tmp_path / "repo"
    config = root / "backend/app/core/config.py"
    env_example = root / "backend/.env.example"
    config.parent.mkdir(parents=True)
    config.write_text(
        "\n".join(
            (
                "agentic_platform_enabled: bool = False",
                "agentic_execution_enabled: bool = False",
                'agentic_model_provider: str = "disabled"',
            )
        ),
        encoding="utf-8",
    )
    env_example.write_text(
        "\n".join(
            (
                "STUDYHUB_AGENTIC_PLATFORM_ENABLED=false",
                "STUDYHUB_AGENTIC_EXECUTION_ENABLED=false",
                "STUDYHUB_AGENTIC_MODEL_PROVIDER=disabled",
            )
        ),
        encoding="utf-8",
    )
    assert all(inspect_production_defaults(config, env_example).values())

    model = tmp_path / "model"
    model.mkdir()
    weights = model / "weights.bin"
    weights.write_bytes(b"frozen-local-model")
    manifest = {
        "files": {
            "weights.bin": {
                "bytes": weights.stat().st_size,
                "sha256": sha256_file(weights),
            }
        }
    }
    _verify_base_export(model, manifest)
    weights.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="size changed"):
        _verify_base_export(model, manifest)
