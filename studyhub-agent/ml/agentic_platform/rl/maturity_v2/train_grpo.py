"""Trajectory-level constrained-token GRPO for the isolated StudyHub Router."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import random
import subprocess
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..reward import RouterRewardPolicy, score_double_ledger
from ..spec import canonical_json, sha256_file
from .actions import RouterActionSpace, build_action_space
from .build_dataset import CRITICAL_BOUNDARY_FAMILIES
from .policy import (
    action_entropy,
    available_action_log_probs,
    create_lora_policy,
    decision_prompt,
    encode_prompts,
    final_token_logits,
    load_lora_policy,
    load_processor,
    trainable_parameter_count,
    true_token_entropy,
)
from .reference_cache import load_reference_cache
from .spec import MaturityRouterState, load_maturity_states
from .trajectory import (
    CreditedDecision,
    TrajectoryRollout,
    TrajectoryStep,
    credit_trajectories,
)

SCHEMA_VERSION = "studyhub.agent.router_rl.trajectory_grpo_config.v2"
ALGORITHM = "trajectory_constrained_token_grpo_v2"
FORBIDDEN_ENDPOINT_VARS = (
    "DATABASE_URL",
    "MYSQL_URL",
    "STUDYHUB_DATABASE_URL",
    "OPENAI_BASE_URL",
    "ANTHROPIC_BASE_URL",
    "STUDYHUB_AGENTIC_MODEL_BASE_URL",
)


@dataclass(frozen=True, slots=True)
class GRPOConfig:
    model_path: Path
    train_path: Path
    reference_cache_path: Path
    output_root: Path
    lora_rank: int
    lora_alpha: int
    lora_dropout: float
    rollout_updates: int
    group_size: int
    material_episodes_per_update: int
    boundary_episodes_per_update: int
    policy_epochs: int
    action_temperature: float
    learning_rate: float
    learning_rate_schedule: str
    learning_rate_decay_optimizer_updates: int
    learning_rate_min_ratio: float
    adam_beta1: float
    adam_beta2: float
    weight_decay: float
    reference_kl_beta: float
    clip_epsilon: float
    entropy_beta: float
    trajectory_discount: float
    terminal_bonus: float
    failure_penalty: float
    max_grad_norm: float
    max_prompt_tokens: int
    checkpoint_every: int
    gradient_checkpointing: bool
    device: str
    formal_run: bool
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> GRPOConfig:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if (
            raw.get("schema_version") != SCHEMA_VERSION
            or raw.get("algorithm") != ALGORITHM
        ):
            raise ValueError("unsupported trajectory GRPO config")
        isolation = raw.get("isolation") or {}
        required_false = (
            "production_access_allowed",
            "paid_material_allowed",
            "test_read_allowed",
            "sealed_read_allowed",
            "production_final_holdout_allowed",
        )
        if any(isolation.get(name) is not False for name in required_false):
            raise ValueError("trajectory GRPO config violates the isolation contract")
        config = cls(
            model_path=Path(raw["model_path"]).resolve(),
            train_path=Path(raw["train_path"]).resolve(),
            reference_cache_path=Path(raw["reference_cache_path"]).resolve(),
            output_root=Path(raw["output_root"]).resolve(),
            lora_rank=int(raw["lora_rank"]),
            lora_alpha=int(raw.get("lora_alpha") or int(raw["lora_rank"]) * 2),
            lora_dropout=float(raw.get("lora_dropout", 0.05)),
            rollout_updates=int(raw["rollout_updates"]),
            group_size=int(raw["group_size"]),
            material_episodes_per_update=int(raw["material_episodes_per_update"]),
            boundary_episodes_per_update=int(raw["boundary_episodes_per_update"]),
            policy_epochs=int(raw["policy_epochs"]),
            action_temperature=float(raw["action_temperature"]),
            learning_rate=float(raw["learning_rate"]),
            learning_rate_schedule=str(raw.get("learning_rate_schedule", "constant")),
            learning_rate_decay_optimizer_updates=int(
                raw.get(
                    "learning_rate_decay_optimizer_updates",
                    int(raw["rollout_updates"]) * int(raw["policy_epochs"]),
                )
            ),
            learning_rate_min_ratio=float(raw.get("learning_rate_min_ratio", 1.0)),
            adam_beta1=float(raw.get("adam_beta1", 0.9)),
            adam_beta2=float(raw.get("adam_beta2", 0.95)),
            weight_decay=float(raw.get("weight_decay", 0.0)),
            reference_kl_beta=float(raw["reference_kl_beta"]),
            clip_epsilon=float(raw["clip_epsilon"]),
            entropy_beta=float(raw.get("entropy_beta", 0.0)),
            trajectory_discount=float(raw["trajectory_discount"]),
            terminal_bonus=float(raw["terminal_bonus"]),
            failure_penalty=float(raw["failure_penalty"]),
            max_grad_norm=float(raw.get("max_grad_norm", 1.0)),
            max_prompt_tokens=int(raw.get("max_prompt_tokens", 4096)),
            checkpoint_every=int(raw["checkpoint_every"]),
            gradient_checkpointing=raw.get("gradient_checkpointing") is True,
            device=str(raw.get("device", "cuda:0")),
            formal_run=raw.get("formal_run") is True,
            raw=raw,
        )
        config.validate()
        return config

    def validate(self) -> None:
        for path in (self.model_path, self.train_path, self.reference_cache_path):
            if not path.exists():
                raise FileNotFoundError(path)
        if self.lora_rank not in {8, 16, 32}:
            raise ValueError("LoRA rank must be one of the preregistered ranks")
        if self.group_size < 2 or self.policy_epochs < 2:
            raise ValueError(
                "GRPO requires group_size >= 2 and at least two policy epochs"
            )
        if self.rollout_updates < 1 or self.material_episodes_per_update < 1:
            raise ValueError("GRPO update and material episode counts must be positive")
        if self.boundary_episodes_per_update < 1:
            raise ValueError("each update must include critical boundary episodes")
        if not 0 < self.action_temperature <= 2:
            raise ValueError("action temperature is outside the supported range")
        if not 0 < self.learning_rate < 1e-3:
            raise ValueError("learning rate is outside the supported range")
        if self.learning_rate_schedule not in {"constant", "linear", "cosine"}:
            raise ValueError("unsupported learning-rate schedule")
        if self.learning_rate_decay_optimizer_updates < 1:
            raise ValueError("learning-rate decay horizon must be positive")
        if not 0 < self.learning_rate_min_ratio <= 1:
            raise ValueError("learning-rate minimum ratio must be in (0, 1]")
        if (
            self.learning_rate_schedule == "constant"
            and self.learning_rate_min_ratio != 1
        ):
            raise ValueError("constant learning rate requires minimum ratio 1")
        if not 0 <= self.reference_kl_beta <= 1 or not 0 < self.clip_epsilon < 1:
            raise ValueError("KL or clipping configuration is invalid")
        if not 0 < self.trajectory_discount <= 1:
            raise ValueError("trajectory discount must be in (0, 1]")
        minimum_rollouts = (
            self.rollout_updates
            * self.group_size
            * (self.material_episodes_per_update + self.boundary_episodes_per_update)
        )
        if self.formal_run and (
            self.rollout_updates < 500 or minimum_rollouts < 10_000
        ):
            raise ValueError(
                "formal GRPO runs require >=500 updates and >=10,000 trajectories"
            )

    @property
    def planned_trajectory_rollouts(self) -> int:
        return (
            self.rollout_updates
            * self.group_size
            * (self.material_episodes_per_update + self.boundary_episodes_per_update)
        )


@dataclass(slots=True)
class DecisionBatch:
    state: MaturityRouterState
    space: RouterActionSpace
    action_indices: list[int]
    old_log_probs: list[float]
    advantages: list[float]
    reference_log_probs: list[float]
    prompt_tokens: int


@dataclass(slots=True)
class CollectedEpisode:
    trajectories: list[TrajectoryRollout]
    decision_batches: list[DecisionBatch]
    reward_rows: list[dict[str, Any]]
    true_token_entropies: list[float]
    action_entropies: list[float]
    prompt_tokens: list[int]


def train_grpo(
    *,
    config_path: Path,
    seed: int,
    output_dir: Path | None = None,
    stop_after: int | None = None,
    resume_from: Path | None = None,
) -> dict[str, Any]:
    _assert_offline_environment()
    config = GRPOConfig.load(config_path)
    run_dir = (
        output_dir.resolve() if output_dir else config.output_root / f"seed_{seed}"
    )
    final_summary_path = run_dir / "run_summary.json"
    if final_summary_path.exists():
        raise FileExistsError(f"GRPO run is already finalized: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = run_dir / "config.snapshot.json"
    if snapshot_path.exists():
        if sha256_file(snapshot_path) != _json_hash(config.raw):
            raise RuntimeError(
                "existing run config snapshot differs from requested config"
            )
    else:
        _write_json(snapshot_path, config.raw)

    states = load_maturity_states(config.train_path, splits={"train"})
    references = load_reference_cache(config.reference_cache_path)
    _verify_reference_cache(states, references)
    episodes = _group_episodes(states)
    schedule = _build_schedule(
        episodes,
        updates=config.rollout_updates,
        material_per_update=config.material_episodes_per_update,
        boundary_per_update=config.boundary_episodes_per_update,
        seed=seed,
    )
    schedule_audit = _audit_schedule(episodes, schedule)
    if set(schedule_audit["boundary_family_counts"]) != set(CRITICAL_BOUNDARY_FAMILIES):
        raise RuntimeError(
            "episode schedule does not cover every critical boundary family"
        )
    schedule_path = run_dir / "episode_schedule.json"
    _write_json(
        schedule_path,
        {
            "seed": seed,
            "updates": schedule,
            "audit": schedule_audit,
            "test_read": False,
            "sealed_read": False,
            "production_access": False,
        },
    )

    import torch
    from transformers.utils import logging as transformers_logging

    transformers_logging.set_verbosity_error()
    transformers_logging.disable_progress_bar()
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    processor = load_processor(config.model_path)
    if resume_from is None:
        policy = create_lora_policy(
            config.model_path,
            device=config.device,
            rank=config.lora_rank,
            alpha=config.lora_alpha,
            dropout=config.lora_dropout,
            gradient_checkpointing=config.gradient_checkpointing,
        )
        start_update = 1
        optimizer_steps = 0
    else:
        checkpoint = _read_json(resume_from / "checkpoint.json")
        if int(checkpoint["seed"]) != seed or checkpoint[
            "config_sha256"
        ] != sha256_file(snapshot_path):
            raise RuntimeError("resume checkpoint does not match seed or config")
        policy = load_lora_policy(
            config.model_path,
            resume_from / "adapter",
            device=config.device,
            trainable=True,
            gradient_checkpointing=config.gradient_checkpointing,
        )
        start_update = int(checkpoint["completed_rollout_updates"]) + 1
        optimizer_steps = int(checkpoint["optimizer_steps"])
    optimizer = torch.optim.AdamW(
        (parameter for parameter in policy.parameters() if parameter.requires_grad),
        lr=config.learning_rate,
        betas=(config.adam_beta1, config.adam_beta2),
        weight_decay=config.weight_decay,
    )
    if resume_from is not None:
        optimizer.load_state_dict(
            torch.load(resume_from / "optimizer.pt", map_location=config.device)
        )

    target_update = min(config.rollout_updates, stop_after or config.rollout_updates)
    if target_update < start_update - 1:
        raise ValueError("stop_after precedes the resume checkpoint")
    metrics_path = run_dir / "trainer_metrics.jsonl"
    trajectories_path = run_dir / "trajectory_rollouts.jsonl"
    _verify_resume_logs(metrics_path, start_update)
    reward_policy = RouterRewardPolicy()
    started = time.perf_counter()
    total_trajectory_rollouts = (
        (start_update - 1)
        * config.group_size
        * (config.material_episodes_per_update + config.boundary_episodes_per_update)
    )
    total_action_rollouts = _count_existing_action_rollouts(trajectories_path)
    trajectory_successes = _count_existing_trajectory_successes(trajectories_path)
    all_update_rows = _read_jsonl(metrics_path) if metrics_path.exists() else []
    for update_index in range(start_update, target_update + 1):
        policy.eval()
        collected: list[CollectedEpisode] = []
        for episode_position, episode_id in enumerate(schedule[update_index - 1]):
            collected.append(
                _collect_episode(
                    policy=policy,
                    processor=processor,
                    states=episodes[episode_id],
                    references=references,
                    config=config,
                    reward_policy=reward_policy,
                    seed=_sampling_seed(
                        seed, update_index, episode_position, episode_id
                    ),
                )
            )
        decision_batches = [
            batch for item in collected for batch in item.decision_batches
        ]
        credited_decisions = sum(
            len(trajectory.steps)
            for item in collected
            for trajectory in item.trajectories
        )
        if credited_decisions != sum(
            len(batch.action_indices) for batch in decision_batches
        ):
            raise RuntimeError("trajectory decisions and policy batches diverged")
        nonzero_advantages = sum(
            abs(value) > 1e-8
            for batch in decision_batches
            for value in batch.advantages
        )

        epoch_metrics: list[dict[str, float]] = []
        # Keep dropout disabled so old/current ratios differ only because of an
        # optimizer step, not because two stochastic forward passes disagree.
        policy.eval()
        for policy_epoch in range(config.policy_epochs):
            current_learning_rate = _scheduled_learning_rate(config, optimizer_steps)
            for parameter_group in optimizer.param_groups:
                parameter_group["lr"] = current_learning_rate
            optimizer.zero_grad(set_to_none=True)
            epoch = _optimize_epoch(
                policy=policy,
                processor=processor,
                batches=decision_batches,
                config=config,
            )
            grad_norm = torch.nn.utils.clip_grad_norm_(
                [
                    parameter
                    for parameter in policy.parameters()
                    if parameter.requires_grad
                ],
                config.max_grad_norm,
            )
            optimizer.step()
            optimizer_steps += 1
            epoch["policy_epoch"] = float(policy_epoch)
            epoch["grad_norm"] = float(grad_norm.detach().item())
            epoch["learning_rate"] = current_learning_rate
            epoch_metrics.append(epoch)

        trajectories = [
            trajectory for item in collected for trajectory in item.trajectories
        ]
        reward_rows = [row for item in collected for row in item.reward_rows]
        total_trajectory_rollouts += len(trajectories)
        total_action_rollouts += credited_decisions
        trajectory_successes += sum(trajectory.completed for trajectory in trajectories)
        update_hacking = Counter(
            value
            for reward_row in reward_rows
            for value in reward_row["reward_hacking_flags"]
        )
        update_hard_gate_failures = Counter(
            value
            for reward_row in reward_rows
            for value in reward_row["failed_hard_gates"]
        )
        update_corrections = Counter(
            value
            for reward_row in reward_rows
            for value in reward_row["constraint_corrections"]
        )
        _append_trajectory_rows(trajectories_path, trajectories, update_index)
        raw_rewards = [float(row["raw_reward"]) for row in reward_rows]
        return_values = [
            decision.return_to_go
            for item in collected
            for decision in credit_trajectories(
                item.trajectories,
                discount=config.trajectory_discount,
                terminal_bonus=config.terminal_bonus,
                failure_penalty=config.failure_penalty,
            )
        ]
        entropy_values = [
            value for item in collected for value in item.true_token_entropies
        ]
        action_entropy_values = [
            value for item in collected for value in item.action_entropies
        ]
        prompt_tokens = [value for item in collected for value in item.prompt_tokens]
        post_update = epoch_metrics[-1]
        row = {
            "rollout_update": update_index,
            "optimizer_steps": optimizer_steps,
            "trajectory_rollouts": len(trajectories),
            "action_rollouts": credited_decisions,
            "nonzero_advantage_fraction": round(
                nonzero_advantages / credited_decisions,
                8,
            ),
            "trajectory_success_rate": round(
                sum(trajectory.completed for trajectory in trajectories)
                / len(trajectories),
                6,
            ),
            "raw_reward_mean": round(sum(raw_rewards) / len(raw_rewards), 6),
            "return_to_go_mean": round(sum(return_values) / len(return_values), 6),
            "true_token_entropy_mean": round(
                sum(entropy_values) / len(entropy_values), 8
            ),
            "action_entropy_mean": round(
                sum(action_entropy_values) / len(action_entropy_values), 8
            ),
            "prompt_tokens_mean": round(sum(prompt_tokens) / len(prompt_tokens), 3),
            "policy_epochs": epoch_metrics,
            "post_update_policy_ratio_mean": round(post_update["ratio_mean"], 8),
            "post_update_policy_ratio_std": round(post_update["ratio_std"], 8),
            "post_update_clip_fraction": round(post_update["clip_fraction"], 8),
            "reference_kl": round(post_update["reference_kl"], 8),
            "learning_rate": post_update["learning_rate"],
            "reward_hacking_flags": dict(sorted(update_hacking.items())),
            "raw_hard_gate_failures": dict(sorted(update_hard_gate_failures.items())),
            "constraint_corrections": dict(sorted(update_corrections.items())),
            "constraint_dependency_absolute_mean": round(
                sum(
                    abs(float(value["constraint_dependency_delta"]))
                    for value in reward_rows
                )
                / len(reward_rows),
                8,
            ),
            "cuda_memory_allocated_mib": round(
                torch.cuda.memory_allocated() / (1024**2), 3
            ),
            "cuda_memory_peak_mib": round(
                torch.cuda.max_memory_allocated() / (1024**2), 3
            ),
        }
        all_update_rows.append(row)
        _append_jsonl(metrics_path, row)
        print(canonical_json(row), flush=True)
        if update_index % config.checkpoint_every == 0 or update_index == target_update:
            _save_checkpoint(
                policy=policy,
                optimizer=optimizer,
                run_dir=run_dir,
                update_index=update_index,
                optimizer_steps=optimizer_steps,
                seed=seed,
                config_sha256=sha256_file(snapshot_path),
            )

    duration = time.perf_counter() - started
    invocation_path = run_dir / "invocation_history.jsonl"
    invocation = {
        "seed": seed,
        "start_rollout_update": start_update,
        "end_rollout_update": target_update,
        "rollout_updates": max(0, target_update - start_update + 1),
        "trajectory_rollouts": max(0, target_update - start_update + 1)
        * config.group_size
        * (config.material_episodes_per_update + config.boundary_episodes_per_update),
        "optimizer_updates": max(0, target_update - start_update + 1)
        * config.policy_epochs,
        "duration_seconds": round(duration, 3),
        "resumed": resume_from is not None,
        "completed_formal_target": target_update == config.rollout_updates,
        "production_access": False,
        "test_read": False,
        "sealed_read": False,
    }
    _append_jsonl(invocation_path, invocation)
    if target_update < config.rollout_updates:
        status = {
            "schema_version": "studyhub.agent.router_rl.partial_run.v2",
            "status": "paused_for_resume_exercise",
            "completed_rollout_updates": target_update,
            "optimizer_steps": optimizer_steps,
            "trajectory_rollouts": total_trajectory_rollouts,
            "action_rollouts": total_action_rollouts,
            "duration_seconds_this_invocation": round(duration, 3),
            "resume_checkpoint": str(
                (run_dir / "checkpoints" / f"update_{target_update:04d}").resolve()
            ),
            "production_access": False,
            "test_read": False,
            "sealed_read": False,
        }
        _write_json(run_dir / "partial_status.json", status)
        _cleanup(policy, optimizer)
        return status

    adapter_dir = run_dir / "adapter"
    policy.save_pretrained(adapter_dir, safe_serialization=True)
    adapter_path = adapter_dir / "adapter_model.safetensors"
    if not adapter_path.is_file():
        raise RuntimeError("final GRPO adapter was not written")
    stability = _stability_summary(all_update_rows)
    hacking_counts = _aggregate_counter(all_update_rows, "reward_hacking_flags")
    hard_gate_failures = _aggregate_counter(all_update_rows, "raw_hard_gate_failures")
    correction_counts = _aggregate_counter(all_update_rows, "constraint_corrections")
    invocations = _read_jsonl(invocation_path)
    total_duration = sum(float(value["duration_seconds"]) for value in invocations)
    summary = {
        "schema_version": "studyhub.agent.router_rl.trajectory_grpo_run.v2",
        "algorithm": ALGORITHM,
        "seed": seed,
        "formal_run": config.formal_run,
        "training_succeeded": True,
        "duration_seconds_this_invocation": round(duration, 3),
        "duration_seconds_total": round(total_duration, 3),
        "trajectory_rollouts_per_second_this_invocation": round(
            (
                (target_update - start_update + 1)
                * config.group_size
                * (
                    config.material_episodes_per_update
                    + config.boundary_episodes_per_update
                )
            )
            / duration,
            6,
        ),
        "trajectory_rollouts_per_second_total": round(
            total_trajectory_rollouts / total_duration,
            6,
        ),
        "rollout_updates": config.rollout_updates,
        "optimizer_updates": optimizer_steps,
        "trajectory_rollouts": total_trajectory_rollouts,
        "action_rollouts": total_action_rollouts,
        "trajectory_success_rate": round(
            trajectory_successes / total_trajectory_rollouts,
            6,
        ),
        "minimum_trajectory_rollouts_satisfied": total_trajectory_rollouts >= 10_000,
        "minimum_optimizer_updates_satisfied": optimizer_steps >= 500,
        "lora": {
            "rank": config.lora_rank,
            "alpha": config.lora_alpha,
            "dropout": config.lora_dropout,
            "trainable_parameters": trainable_parameter_count(policy),
        },
        "objective": {
            "trajectory_return_to_go": True,
            "group_relative_advantage": True,
            "clipped_post_update_policy_ratio": True,
            "frozen_reference_kl": True,
            "true_token_entropy": True,
            "raw_policy_reward_only": True,
            "executable_ledger_used_for_gradient": False,
            "deterministic_constraints_rewarded": False,
            "trajectory_discount": config.trajectory_discount,
            "reference_kl_beta": config.reference_kl_beta,
        },
        "optimization": {
            "learning_rate": config.learning_rate,
            "learning_rate_schedule": config.learning_rate_schedule,
            "learning_rate_decay_optimizer_updates": (
                config.learning_rate_decay_optimizer_updates
            ),
            "learning_rate_min_ratio": config.learning_rate_min_ratio,
            "final_learning_rate": all_update_rows[-1]["learning_rate"],
            "policy_epochs": config.policy_epochs,
        },
        "schedule_audit": schedule_audit,
        "stability": stability,
        "reward_hacking_flags": dict(sorted(hacking_counts.items())),
        "raw_hard_gate_failures": dict(sorted(hard_gate_failures.items())),
        "constraint_corrections": dict(sorted(correction_counts.items())),
        "checkpoint_resume_supported": True,
        "checkpoint_resume_exercised": resume_from is not None,
        "gpu": {
            "name": torch.cuda.get_device_name(),
            "peak_memory_mib": round(torch.cuda.max_memory_allocated() / (1024**2), 3),
        },
        "artifacts": {
            "adapter_path": str(adapter_dir.resolve()),
            "adapter_sha256": sha256_file(adapter_path),
            "metrics_path": str(metrics_path.resolve()),
            "metrics_sha256": sha256_file(metrics_path),
            "trajectories_path": str(trajectories_path.resolve()),
            "trajectories_sha256": sha256_file(trajectories_path),
            "invocation_history_path": str(invocation_path.resolve()),
            "invocation_history_sha256": sha256_file(invocation_path),
            "episode_schedule_path": str(schedule_path.resolve()),
            "episode_schedule_sha256": sha256_file(schedule_path),
        },
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
    _write_json(final_summary_path, summary)
    _write_json(
        run_dir / "run_manifest.json",
        {
            "schema_version": "studyhub.agent.router_rl.training_manifest.v2",
            "git_commit": _git_commit(),
            "config_sha256": sha256_file(snapshot_path),
            "train_sha256": sha256_file(config.train_path),
            "reference_cache_sha256": sha256_file(config.reference_cache_path),
            "implementation_sha256": sha256_file(Path(__file__)),
            "episode_schedule_sha256": sha256_file(schedule_path),
            "summary_sha256": sha256_file(final_summary_path),
            "production_access": False,
            "test_read": False,
            "sealed_read": False,
        },
    )
    _cleanup(policy, optimizer)
    return summary


def _collect_episode(
    *,
    policy: Any,
    processor: Any,
    states: list[MaturityRouterState],
    references: dict[str, dict[str, Any]],
    config: GRPOConfig,
    reward_policy: RouterRewardPolicy,
    seed: int,
) -> CollectedEpisode:
    import torch

    group_size = config.group_size
    trajectory_steps: list[list[TrajectoryStep]] = [[] for _ in range(group_size)]
    active = [True] * group_size
    completed = [False] * group_size
    pending: list[dict[str, Any]] = []
    reward_rows: list[dict[str, Any]] = []
    token_entropies: list[float] = []
    action_entropies: list[float] = []
    prompt_tokens: list[int] = []
    generator = torch.Generator(device="cpu")
    generator.manual_seed(seed)
    for state in states:
        active_indices = [index for index, value in enumerate(active) if value]
        if not active_indices:
            break
        space = build_action_space(state)
        prompt = decision_prompt(processor, state, space)
        encoded = encode_prompts(
            processor,
            [prompt],
            device=config.device,
            max_prompt_tokens=config.max_prompt_tokens,
        )
        with torch.no_grad():
            full_logits = final_token_logits(policy, encoded)[0]
            log_probs = available_action_log_probs(
                full_logits,
                space=space,
                tokenizer=processor.tokenizer,
                temperature=config.action_temperature,
            )
        reference = references[state.state_id]
        if list(space.routes) != list(reference["routes"]):
            raise RuntimeError(f"reference action order mismatch for {state.state_id}")
        sampled = torch.multinomial(
            log_probs.exp().detach().cpu(),
            num_samples=len(active_indices),
            replacement=True,
            generator=generator,
        ).tolist()
        sampled_old_log_probs: list[float] = []
        for rollout_index, action_index in zip(active_indices, sampled, strict=True):
            candidate = space.candidates[action_index]
            ledger = score_double_ledger(
                candidate.output, state, reward_policy=reward_policy
            )
            success = candidate.route == space.oracle_route
            trajectory_steps[rollout_index].append(
                TrajectoryStep(
                    state_id=state.state_id,
                    step_index=state.step_index,
                    action_code=candidate.code,
                    reward=ledger.raw.policy_reward,
                    success_transition=success,
                )
            )
            sampled_old_log_probs.append(float(log_probs[action_index].item()))
            if not success:
                active[rollout_index] = False
            elif state.terminal:
                active[rollout_index] = False
                completed[rollout_index] = True
            reward_rows.append(
                {
                    "state_id": state.state_id,
                    "family": state.family,
                    "route": candidate.route,
                    "oracle_route": space.oracle_route,
                    "raw_reward": ledger.raw.policy_reward,
                    "reward_hacking_flags": list(ledger.raw.reward_hacking_flags),
                    "failed_hard_gates": [
                        name
                        for name, passed in ledger.raw.hard_gates.items()
                        if not passed
                    ],
                    "constraint_corrections": list(ledger.constraint_corrections),
                    "constraint_dependency_delta": ledger.constraint_dependency_delta,
                }
            )
        reference_log_probs = torch.log_softmax(
            torch.tensor(reference["log_probs"], dtype=torch.float32)
            / config.action_temperature,
            dim=-1,
        ).tolist()
        pending.append(
            {
                "state": state,
                "space": space,
                "active_indices": active_indices,
                "action_indices": sampled,
                "old_log_probs": sampled_old_log_probs,
                "reference_log_probs": reference_log_probs,
                "prompt_tokens": int(encoded["attention_mask"].sum().item()),
            }
        )
        token_entropies.append(float(true_token_entropy(full_logits).item()))
        action_entropies.append(float(action_entropy(log_probs).item()))
        prompt_tokens.append(int(encoded["attention_mask"].sum().item()))
    trajectories = [
        TrajectoryRollout(
            episode_id=states[0].episode_id,
            rollout_index=index,
            steps=tuple(steps),
            completed=completed[index],
        )
        for index, steps in enumerate(trajectory_steps)
    ]
    credited = credit_trajectories(
        trajectories,
        discount=config.trajectory_discount,
        terminal_bonus=config.terminal_bonus,
        failure_penalty=config.failure_penalty,
    )
    credit_map: dict[tuple[str, int], CreditedDecision] = {
        (decision.state_id, decision.rollout_index): decision for decision in credited
    }
    batches: list[DecisionBatch] = []
    for item in pending:
        batches.append(
            DecisionBatch(
                state=item["state"],
                space=item["space"],
                action_indices=item["action_indices"],
                old_log_probs=item["old_log_probs"],
                advantages=[
                    credit_map[(item["state"].state_id, rollout_index)].advantage
                    for rollout_index in item["active_indices"]
                ],
                reference_log_probs=item["reference_log_probs"],
                prompt_tokens=item["prompt_tokens"],
            )
        )
    return CollectedEpisode(
        trajectories=trajectories,
        decision_batches=batches,
        reward_rows=reward_rows,
        true_token_entropies=token_entropies,
        action_entropies=action_entropies,
        prompt_tokens=prompt_tokens,
    )


def _optimize_epoch(
    *,
    policy: Any,
    processor: Any,
    batches: list[DecisionBatch],
    config: GRPOConfig,
) -> dict[str, float]:
    import torch

    total_decisions = sum(len(batch.action_indices) for batch in batches)
    ratios: list[Any] = []
    policy_losses: list[float] = []
    kl_values: list[float] = []
    entropy_values: list[float] = []
    total_loss_value = 0.0
    for batch in batches:
        prompt = decision_prompt(processor, batch.state, batch.space)
        encoded = encode_prompts(
            processor,
            [prompt],
            device=config.device,
            max_prompt_tokens=config.max_prompt_tokens,
        )
        full_logits = final_token_logits(policy, encoded)[0]
        log_probs = available_action_log_probs(
            full_logits,
            space=batch.space,
            tokenizer=processor.tokenizer,
            temperature=config.action_temperature,
        )
        action_indices = torch.tensor(
            batch.action_indices, dtype=torch.long, device=config.device
        )
        old_log_probs = torch.tensor(
            batch.old_log_probs, dtype=torch.float32, device=config.device
        )
        advantages = torch.tensor(
            batch.advantages, dtype=torch.float32, device=config.device
        )
        selected = log_probs.index_select(0, action_indices)
        ratio = (selected - old_log_probs).clamp(-8, 8).exp()
        unclipped = ratio * advantages
        clipped = (
            ratio.clamp(1 - config.clip_epsilon, 1 + config.clip_epsilon) * advantages
        )
        policy_loss = -torch.minimum(unclipped, clipped).mean()
        reference = torch.tensor(
            batch.reference_log_probs,
            dtype=torch.float32,
            device=config.device,
        )
        probabilities = log_probs.exp()
        kl = (probabilities * (log_probs - reference)).sum()
        entropy = action_entropy(log_probs)
        weight = len(batch.action_indices) / total_decisions
        loss = weight * (
            policy_loss + config.reference_kl_beta * kl - config.entropy_beta * entropy
        )
        loss.backward()
        ratios.append(ratio.detach().cpu())
        policy_losses.append(float(policy_loss.detach().item()) * weight)
        kl_values.append(float(kl.detach().item()) * weight)
        entropy_values.append(float(entropy.detach().item()) * weight)
        total_loss_value += float(loss.detach().item())
    flat_ratios = torch.cat(ratios)
    clip_fraction = (
        (
            (flat_ratios < 1 - config.clip_epsilon)
            | (flat_ratios > 1 + config.clip_epsilon)
        )
        .float()
        .mean()
    )
    return {
        "loss": total_loss_value,
        "policy_loss": sum(policy_losses),
        "reference_kl": sum(kl_values),
        "action_entropy": sum(entropy_values),
        "ratio_mean": float(flat_ratios.mean().item()),
        "ratio_std": float(flat_ratios.std(unbiased=False).item()),
        "ratio_min": float(flat_ratios.min().item()),
        "ratio_max": float(flat_ratios.max().item()),
        "clip_fraction": float(clip_fraction.item()),
    }


def _group_episodes(
    states: list[MaturityRouterState],
) -> dict[str, list[MaturityRouterState]]:
    grouped: dict[str, list[MaturityRouterState]] = defaultdict(list)
    for state in states:
        grouped[state.episode_id].append(state)
    for episode_id, values in grouped.items():
        values.sort(key=lambda state: state.step_index)
        if [state.step_index for state in values] != list(range(len(values))):
            raise ValueError(f"invalid episode graph: {episode_id}")
    return dict(grouped)


def _build_schedule(
    episodes: dict[str, list[MaturityRouterState]],
    *,
    updates: int,
    material_per_update: int,
    boundary_per_update: int,
    seed: int,
) -> list[list[str]]:
    material = sorted(key for key, values in episodes.items() if len(values) > 1)
    boundary_by_family: dict[str, list[str]] = defaultdict(list)
    for episode_id, values in episodes.items():
        if len(values) == 1:
            boundary_by_family[values[0].family].append(episode_id)
    if not material or not boundary_by_family:
        raise ValueError("training requires both multi-step and boundary episodes")
    missing_families = set(CRITICAL_BOUNDARY_FAMILIES) - set(boundary_by_family)
    if missing_families:
        raise ValueError(
            "training data lacks critical boundary families: "
            + ", ".join(sorted(missing_families))
        )
    rng = random.Random(seed)
    material_stream = _cycling_shuffle(material, rng)
    family_stream = _cycling_shuffle(sorted(boundary_by_family), rng)
    boundary_streams = {
        family: _cycling_shuffle(sorted(episode_ids), rng)
        for family, episode_ids in boundary_by_family.items()
    }
    return [
        [
            *(next(material_stream) for _ in range(material_per_update)),
            *(
                next(boundary_streams[next(family_stream)])
                for _ in range(boundary_per_update)
            ),
        ]
        for _ in range(updates)
    ]


def _audit_schedule(
    episodes: dict[str, list[MaturityRouterState]],
    schedule: list[list[str]],
) -> dict[str, Any]:
    material_counts: Counter[str] = Counter()
    boundary_counts: Counter[str] = Counter()
    boundary_family_counts: Counter[str] = Counter()
    for update in schedule:
        for episode_id in update:
            states = episodes[episode_id]
            if len(states) > 1:
                material_counts[episode_id] += 1
            else:
                boundary_counts[episode_id] += 1
                boundary_family_counts[states[0].family] += 1
    family_values = list(boundary_family_counts.values())
    return {
        "updates": len(schedule),
        "material_selections": sum(material_counts.values()),
        "boundary_selections": sum(boundary_counts.values()),
        "unique_material_episodes": len(material_counts),
        "unique_boundary_episodes": len(boundary_counts),
        "boundary_family_counts": dict(sorted(boundary_family_counts.items())),
        "boundary_family_max_min_gap": (
            max(family_values) - min(family_values) if family_values else None
        ),
        "stratified_boundary_rotation": True,
    }


def _scheduled_learning_rate(config: GRPOConfig, optimizer_step: int) -> float:
    if config.learning_rate_schedule == "constant":
        return config.learning_rate
    progress = min(
        max(optimizer_step / config.learning_rate_decay_optimizer_updates, 0.0),
        1.0,
    )
    if config.learning_rate_schedule == "linear":
        multiplier = 1.0 - progress
    else:
        multiplier = 0.5 * (1.0 + math.cos(math.pi * progress))
    multiplier = (
        config.learning_rate_min_ratio
        + (1.0 - config.learning_rate_min_ratio) * multiplier
    )
    return config.learning_rate * multiplier


def _cycling_shuffle(values: list[str], rng: random.Random):
    while True:
        current = list(values)
        rng.shuffle(current)
        yield from current


def _verify_reference_cache(
    states: list[MaturityRouterState],
    references: dict[str, dict[str, Any]],
) -> None:
    state_ids = {state.state_id for state in states}
    if set(references) != state_ids:
        raise ValueError("reference cache does not exactly cover the training states")
    for state in states:
        space = build_action_space(state)
        reference = references[state.state_id]
        if list(space.routes) != list(reference["routes"]):
            raise ValueError(f"reference routes changed for {state.state_id}")
        probabilities = sum(math.exp(float(value)) for value in reference["log_probs"])
        if not math.isclose(probabilities, 1.0, rel_tol=1e-5, abs_tol=1e-5):
            raise ValueError(
                f"reference distribution is not normalized for {state.state_id}"
            )


def _append_trajectory_rows(
    path: Path,
    trajectories: list[TrajectoryRollout],
    update_index: int,
) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for trajectory in trajectories:
            handle.write(
                canonical_json(
                    {
                        "rollout_update": update_index,
                        "episode_id": trajectory.episode_id,
                        "rollout_index": trajectory.rollout_index,
                        "completed": trajectory.completed,
                        "steps": [asdict(step) for step in trajectory.steps],
                    }
                )
                + "\n"
            )


def _save_checkpoint(
    *,
    policy: Any,
    optimizer: Any,
    run_dir: Path,
    update_index: int,
    optimizer_steps: int,
    seed: int,
    config_sha256: str,
) -> None:
    import torch

    checkpoint_dir = run_dir / "checkpoints" / f"update_{update_index:04d}"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    policy.save_pretrained(checkpoint_dir / "adapter", safe_serialization=True)
    torch.save(optimizer.state_dict(), checkpoint_dir / "optimizer.pt")
    _write_json(
        checkpoint_dir / "checkpoint.json",
        {
            "schema_version": "studyhub.agent.router_rl.checkpoint.v2",
            "seed": seed,
            "completed_rollout_updates": update_index,
            "optimizer_steps": optimizer_steps,
            "config_sha256": config_sha256,
            "adapter_sha256": sha256_file(
                checkpoint_dir / "adapter" / "adapter_model.safetensors"
            ),
            "optimizer_sha256": sha256_file(checkpoint_dir / "optimizer.pt"),
            "test_read": False,
            "sealed_read": False,
            "production_access": False,
        },
    )


def _stability_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [row["post_update_policy_ratio_mean"] for row in rows]
    clips = [row["post_update_clip_fraction"] for row in rows]
    kls = [row["reference_kl"] for row in rows]
    entropies = [row["true_token_entropy_mean"] for row in rows]
    advantage_fractions = [row["nonzero_advantage_fraction"] for row in rows]
    learning_rates = [row["learning_rate"] for row in rows]
    return {
        "finite": all(
            math.isfinite(float(value))
            for row in rows
            for value in (
                row["raw_reward_mean"],
                row["return_to_go_mean"],
                row["post_update_policy_ratio_mean"],
                row["reference_kl"],
                row["true_token_entropy_mean"],
                row["learning_rate"],
            )
        ),
        "mean_post_update_policy_ratio": round(sum(values) / len(values), 8),
        "post_update_policy_ratio_observed": any(
            abs(float(row["post_update_policy_ratio_std"])) > 1e-8 for row in rows
        ),
        "mean_clip_fraction": round(sum(clips) / len(clips), 8),
        "clip_fraction_measured": all(0 <= value <= 1 for value in clips),
        "mean_reference_kl": round(sum(kls) / len(kls), 8),
        "max_reference_kl": max(kls),
        "mean_true_token_entropy": round(sum(entropies) / len(entropies), 8),
        "initial_learning_rate": learning_rates[0],
        "final_learning_rate": learning_rates[-1],
        "learning_rate_decay_observed": learning_rates[-1] < learning_rates[0],
        "true_token_entropy_observed": all(value > 0 for value in entropies),
        "mean_nonzero_advantage_fraction": round(
            sum(advantage_fractions) / len(advantage_fractions),
            8,
        ),
        "trajectory_credit_signal_observed": any(
            value > 0 for value in advantage_fractions
        ),
    }


def _aggregate_counter(rows: list[dict[str, Any]], key: str) -> Counter[str]:
    result: Counter[str] = Counter()
    for row in rows:
        value = row.get(key)
        if isinstance(value, dict):
            result.update({str(name): int(count) for name, count in value.items()})
    return result


def _sampling_seed(seed: int, update: int, position: int, episode_id: str) -> int:
    value = f"{seed}:{update}:{position}:{episode_id}".encode()
    return int(hashlib.sha256(value).hexdigest()[:15], 16)


def _verify_resume_logs(path: Path, start_update: int) -> None:
    existing = _read_jsonl(path) if path.exists() else []
    if len(existing) != start_update - 1:
        raise RuntimeError(
            f"metrics log has {len(existing)} updates but resume expects {start_update - 1}"
        )


def _count_existing_action_rollouts(path: Path) -> int:
    return (
        sum(len(row.get("steps") or []) for row in _read_jsonl(path))
        if path.exists()
        else 0
    )


def _count_existing_trajectory_successes(path: Path) -> int:
    return (
        sum(bool(row.get("completed")) for row in _read_jsonl(path))
        if path.exists()
        else 0
    )


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _append_jsonl(path: Path, value: object) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_json(value) + "\n")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _json_hash(value: object) -> str:
    return hashlib.sha256(
        (
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode()
    ).hexdigest()


def _git_commit() -> str:
    return subprocess.check_output(
        ["git", "-C", str(Path(__file__).resolve().parents[4]), "rev-parse", "HEAD"],
        text=True,
    ).strip()


def _cleanup(policy: Any, optimizer: Any) -> None:
    import torch

    del policy, optimizer
    gc.collect()
    torch.cuda.empty_cache()


def _assert_offline_environment() -> None:
    active = [name for name in FORBIDDEN_ENDPOINT_VARS if os.getenv(name)]
    if active:
        raise RuntimeError(f"offline GRPO refuses configured endpoints: {active}")
    if os.getenv("HF_HUB_OFFLINE") != "1" or os.getenv("TRANSFORMERS_OFFLINE") != "1":
        raise RuntimeError("offline GRPO requires local-only Hugging Face mode")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--stop-after", type=int)
    parser.add_argument("--resume-from", type=Path)
    args = parser.parse_args()
    result = train_grpo(
        config_path=args.config.resolve(),
        seed=args.seed,
        output_dir=args.output_dir.resolve() if args.output_dir else None,
        stop_after=args.stop_after,
        resume_from=args.resume_from.resolve() if args.resume_from else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
