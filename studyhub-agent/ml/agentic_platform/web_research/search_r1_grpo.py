from __future__ import annotations

import argparse
import asyncio
import gc
import json
import math
import os
import random
import statistics
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.agentic_platform.deepresearch.state import DeepResearchState
from app.agentic_platform.domain.hashing import canonical_hash, canonical_json

from .local_policy import (
    build_research_decision_messages,
    extract_first_json_object,
    parse_research_decision,
)
from .rl_environment import (
    FrozenWebResearchEnvironment,
    WebRLPilotScenario,
    build_web_rl_pilot_scenarios,
)


SEARCH_R1_REFERENCE_COMMIT = "598e61bd1d36895726d28a8d06b3a15bed19f5d3"
FORBIDDEN_ENDPOINT_VARS = (
    "DATABASE_URL",
    "MYSQL_URL",
    "STUDYHUB_DATABASE_URL",
    "OPENAI_BASE_URL",
    "ANTHROPIC_BASE_URL",
    "STUDYHUB_AGENTIC_MODEL_BASE_URL",
    "STUDYHUB_WEB_ROUTER_EVAL_MODEL_BASE_URL",
)


@dataclass(slots=True)
class SearchR1Turn:
    turn_index: int
    state_hash: str
    prompt: str
    prompt_tokens: int
    response_token_ids: list[int]
    raw_generated: str
    structured_output_valid: bool
    prediction_error_type: str | None
    action_type: str | None
    transition_valid: bool
    observation_type: str
    old_log_probs: list[float] = field(default_factory=list)
    reference_log_probs: list[float] = field(default_factory=list)
    advantage: float = 0.0


@dataclass(slots=True)
class SearchR1Trajectory:
    scenario_id: str
    split: str
    family: str
    rollout_index: int
    turns: list[SearchR1Turn]
    completed: bool
    reward: float
    advantage: float = 0.0


def evaluate_search_r1_adapter(
    *,
    model_path: Path,
    adapter_path: Path,
    output_dir: Path,
    split: str,
    max_turns: int = 4,
    max_new_tokens: int = 256,
    device: str = "cuda",
) -> dict[str, object]:
    """Evaluate a frozen adapter on one untouched multi-turn scenario split."""

    _assert_offline()
    if split not in {"validation", "test"}:
        raise ValueError("Search-R1 adapter evaluation supports validation or test")
    if not model_path.is_dir() or not adapter_path.is_dir():
        raise FileNotFoundError("adapter evaluation requires a local model and adapter")
    if output_dir.exists():
        raise FileExistsError(output_dir)
    if max_turns <= 0 or max_new_tokens <= 0:
        raise ValueError("adapter evaluation limits must be positive")

    import torch
    from peft import PeftModel
    from transformers import AutoModelForMultimodalLM, AutoProcessor
    from transformers.utils import logging as transformers_logging

    transformers_logging.set_verbosity_error()
    transformers_logging.disable_progress_bar()
    if device.startswith("cuda"):
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(device)
    processor = AutoProcessor.from_pretrained(
        model_path,
        trust_remote_code=True,
        local_files_only=True,
    )
    processor.tokenizer.padding_side = "left"
    base = _load_base_model(AutoModelForMultimodalLM, model_path, device)
    actor = PeftModel.from_pretrained(base, adapter_path, is_trainable=False)
    actor.eval()
    scenarios = [item for item in build_web_rl_pilot_scenarios() if item.split == split]
    started = time.perf_counter()
    evaluation = asyncio.run(
        _evaluate_greedy(
            actor,
            processor,
            scenarios,
            max_turns=max_turns,
            max_new_tokens=max_new_tokens,
            device=device,
        )
    )
    elapsed = time.perf_counter() - started
    gate_passed = (
        evaluation["completion_rate"] == 1.0
        and evaluation["structured_trajectory_rate"] == 1.0
        and all(
            metrics["completion_rate"] == 1.0
            for metrics in evaluation["families"].values()
        )
    )
    summary: dict[str, object] = {
        "schema_version": "studyhub.deepresearch.search_r1_adapter_eval.v1",
        "split": split,
        "adapter_path": str(adapter_path.resolve()),
        "evaluation": evaluation,
        "gate": {
            "passed": gate_passed,
            "minimum_completion_rate": 1.0,
            "minimum_structured_trajectory_rate": 1.0,
            "minimum_family_completion_rate": 1.0,
        },
        "runtime": {
            "elapsed_seconds": round(elapsed, 3),
            "peak_cuda_memory_mib": (
                round(torch.cuda.max_memory_allocated(device) / (1024**2), 3)
                if device.startswith("cuda")
                else None
            ),
        },
        "isolation": {
            "production_api_called": False,
            "production_database_accessed": False,
            "live_web_called": False,
            "paid_material_used": False,
            "optimizer_created": False,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    del actor, base
    gc.collect()
    if device.startswith("cuda"):
        torch.cuda.empty_cache()
    return summary


def run_search_r1_grpo_pilot(
    *,
    model_path: Path,
    sft_adapter_path: Path,
    output_dir: Path,
    seed: int = 7703,
    updates: int = 1,
    group_size: int = 5,
    max_turns: int = 4,
    max_new_tokens: int = 256,
    temperature: float = 1.0,
    learning_rate: float = 5e-7,
    clip_ratio: float = 0.2,
    kl_loss_coef: float = 0.001,
    device: str = "cuda",
) -> dict[str, object]:
    """Run a small, isolated port of Search-R1 outcome-GRPO on StudyHub states."""

    _assert_offline()
    _validate_config(
        model_path=model_path,
        adapter_path=sft_adapter_path,
        output_dir=output_dir,
        updates=updates,
        group_size=group_size,
        max_turns=max_turns,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
        learning_rate=learning_rate,
        clip_ratio=clip_ratio,
        kl_loss_coef=kl_loss_coef,
    )
    import torch
    from peft import PeftModel
    from transformers import AutoModelForMultimodalLM, AutoProcessor
    from transformers.utils import logging as transformers_logging

    transformers_logging.set_verbosity_error()
    transformers_logging.disable_progress_bar()
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    if device.startswith("cuda"):
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(device)
    processor = AutoProcessor.from_pretrained(
        model_path,
        trust_remote_code=True,
        local_files_only=True,
    )
    processor.tokenizer.padding_side = "left"
    actor_base = _load_base_model(AutoModelForMultimodalLM, model_path, device)
    actor = PeftModel.from_pretrained(
        actor_base,
        sft_adapter_path,
        is_trainable=True,
    )
    reference_base = _load_base_model(
        AutoModelForMultimodalLM,
        model_path,
        device,
    )
    reference = PeftModel.from_pretrained(
        reference_base,
        sft_adapter_path,
        is_trainable=False,
    )
    for parameter in actor.parameters():
        if parameter.requires_grad:
            parameter.data = parameter.data.float()
    reference.eval()
    actor.eval()
    optimizer = torch.optim.AdamW(
        [parameter for parameter in actor.parameters() if parameter.requires_grad],
        lr=learning_rate,
        betas=(0.9, 0.95),
        weight_decay=0.0,
    )
    scenarios = build_web_rl_pilot_scenarios()
    train_scenarios = [item for item in scenarios if item.split == "train"]
    validation_scenarios = [item for item in scenarios if item.split == "validation"]
    started = time.perf_counter()
    baseline_validation = asyncio.run(
        _evaluate_greedy(
            actor,
            processor,
            validation_scenarios,
            max_turns=max_turns,
            max_new_tokens=max_new_tokens,
            device=device,
        )
    )
    all_training_trajectories: list[SearchR1Trajectory] = []
    update_rows: list[dict[str, object]] = []
    for update_index in range(updates):
        selected = _stratified_training_selection(train_scenarios, update_index)
        update_trajectories: list[SearchR1Trajectory] = []
        for scenario in selected:
            group = asyncio.run(
                _rollout_group(
                    actor,
                    processor,
                    scenario,
                    group_size=group_size,
                    seed=seed + update_index * 1_000,
                    max_turns=max_turns,
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                    device=device,
                    do_sample=True,
                )
            )
            assign_group_outcome_advantages(group)
            update_trajectories.extend(group)
        trainable_turns = [
            turn
            for trajectory in update_trajectories
            for turn in trajectory.turns
            if turn.response_token_ids
        ]
        _attach_old_and_reference_log_probs(
            actor,
            reference,
            processor,
            trainable_turns,
            temperature=temperature,
            device=device,
        )
        optimization = _grpo_update(
            actor,
            optimizer,
            processor,
            trainable_turns,
            temperature=temperature,
            clip_ratio=clip_ratio,
            kl_loss_coef=kl_loss_coef,
            device=device,
        )
        all_training_trajectories.extend(update_trajectories)
        update_row = {
            "update": update_index + 1,
            "scenarios": len(selected),
            "trajectories": len(update_trajectories),
            "completion_rate": _rate(item.completed for item in update_trajectories),
            "reward_mean": _mean(item.reward for item in update_trajectories),
            "reward_std": _population_std(item.reward for item in update_trajectories),
            "nonzero_advantage_trajectories": sum(
                abs(item.advantage) > 1e-8 for item in update_trajectories
            ),
            **optimization,
        }
        update_rows.append(update_row)
        print(canonical_json(update_row), flush=True)

    actor.eval()
    final_validation = asyncio.run(
        _evaluate_greedy(
            actor,
            processor,
            validation_scenarios,
            max_turns=max_turns,
            max_new_tokens=max_new_tokens,
            device=device,
        )
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    adapter_dir = output_dir / "adapter"
    actor.save_pretrained(adapter_dir)
    trajectory_path = output_dir / "trajectory_rollouts.jsonl"
    trajectory_path.write_text(
        "".join(
            canonical_json(_trajectory_artifact_row(item)) + "\n"
            for item in all_training_trajectories
        ),
        encoding="utf-8",
    )
    elapsed = time.perf_counter() - started
    summary: dict[str, object] = {
        "schema_version": "studyhub.deepresearch.search_r1_grpo_pilot.v1",
        "algorithm": "search_r1_outcome_grpo_state_masked",
        "reference": {
            "repository": "PeterGriffinJin/Search-R1",
            "commit": SEARCH_R1_REFERENCE_COMMIT,
            "borrowed_contracts": [
                "multi_turn_generation_environment_loop",
                "group_relative_outcome_advantage",
                "state_observation_token_masking",
                "token_level_ppo_clip",
                "low_variance_reference_kl",
            ],
        },
        "config": {
            "seed": seed,
            "updates": updates,
            "group_size": group_size,
            "max_turns": max_turns,
            "max_new_tokens": max_new_tokens,
            "temperature": temperature,
            "learning_rate": learning_rate,
            "clip_ratio": clip_ratio,
            "kl_loss_coef": kl_loss_coef,
        },
        "sft_adapter_path": str(sft_adapter_path.resolve()),
        "rl_adapter_path": str(adapter_dir.resolve()),
        "baseline_validation": baseline_validation,
        "final_validation": final_validation,
        "updates": update_rows,
        "training": {
            "trajectories": len(all_training_trajectories),
            "completed": sum(item.completed for item in all_training_trajectories),
            "completion_rate": _rate(
                item.completed for item in all_training_trajectories
            ),
            "reward_mean": _mean(item.reward for item in all_training_trajectories),
            "response_tokens": sum(
                len(turn.response_token_ids)
                for item in all_training_trajectories
                for turn in item.turns
            ),
            "masked_state_tokens": sum(
                turn.prompt_tokens
                for item in all_training_trajectories
                for turn in item.turns
            ),
        },
        "runtime": {
            "elapsed_seconds": round(elapsed, 3),
            "peak_cuda_memory_mib": (
                round(torch.cuda.max_memory_allocated(device) / (1024**2), 3)
                if device.startswith("cuda")
                else None
            ),
        },
        "isolation": {
            "production_api_called": False,
            "production_database_accessed": False,
            "live_web_called": False,
            "paid_material_used": False,
            "test_split_read": False,
        },
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    del actor, reference, actor_base, reference_base
    gc.collect()
    if device.startswith("cuda"):
        torch.cuda.empty_cache()
    return summary


async def _evaluate_greedy(
    actor: Any,
    processor: Any,
    scenarios: list[WebRLPilotScenario],
    *,
    max_turns: int,
    max_new_tokens: int,
    device: str,
) -> dict[str, object]:
    trajectories: list[SearchR1Trajectory] = []
    for scenario in scenarios:
        trajectories.extend(
            await _rollout_group(
                actor,
                processor,
                scenario,
                group_size=1,
                seed=0,
                max_turns=max_turns,
                max_new_tokens=max_new_tokens,
                temperature=1.0,
                device=device,
                do_sample=False,
            )
        )
    return {
        "scenarios": len(trajectories),
        "completion_rate": _rate(item.completed for item in trajectories),
        "structured_trajectory_rate": _rate(
            all(turn.structured_output_valid for turn in item.turns)
            for item in trajectories
        ),
        "reward_mean": _mean(item.reward for item in trajectories),
        "families": {
            family: {
                "completion_rate": _rate(item.completed for item in items),
                "reward_mean": _mean(item.reward for item in items),
            }
            for family, items in _group_by_family(trajectories).items()
        },
    }


async def _rollout_group(
    actor: Any,
    processor: Any,
    scenario: WebRLPilotScenario,
    *,
    group_size: int,
    seed: int,
    max_turns: int,
    max_new_tokens: int,
    temperature: float,
    device: str,
    do_sample: bool,
) -> list[SearchR1Trajectory]:
    import torch

    torch.manual_seed(seed + int(canonical_hash(scenario.scenario_id)[:8], 16))
    environments = [FrozenWebResearchEnvironment() for _index in range(group_size)]
    states = [
        await environment.reset(scenario, seed + rollout_index)
        for rollout_index, environment in enumerate(environments)
    ]
    trajectories = [
        SearchR1Trajectory(
            scenario_id=scenario.scenario_id,
            split=scenario.split,
            family=scenario.family,
            rollout_index=rollout_index,
            turns=[],
            completed=False,
            reward=0.0,
        )
        for rollout_index in range(group_size)
    ]
    active = list(range(group_size))
    actor.eval()
    for turn_index in range(max_turns):
        if not active:
            break
        prompts = [_render_prompt(processor, states[index]) for index in active]
        state_hashes = [canonical_hash(states[index]) for index in active]
        generated = _generate_responses(
            actor,
            processor,
            prompts,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            device=device,
            do_sample=do_sample,
        )
        next_active: list[int] = []
        for active_index, prompt, state_hash, (raw, response_ids) in zip(
            active,
            prompts,
            state_hashes,
            generated,
            strict=True,
        ):
            decision, error_type = parse_research_decision(raw)
            transition_valid = False
            observation_type = "invalid_model_output"
            done = True
            completed = False
            if decision is not None:
                result = await environments[active_index].step(decision)
                transition_valid = result.action_correct
                observation_type = result.observation_type
                done = result.done
                completed = result.completed
                states[active_index] = result.state
            turn = SearchR1Turn(
                turn_index=turn_index,
                state_hash=state_hash,
                prompt=prompt,
                prompt_tokens=len(
                    processor.tokenizer(
                        prompt,
                        add_special_tokens=False,
                    ).input_ids
                ),
                response_token_ids=response_ids,
                raw_generated=raw,
                structured_output_valid=decision is not None,
                prediction_error_type=error_type,
                action_type=(
                    decision.action_type.value if decision is not None else None
                ),
                transition_valid=transition_valid,
                observation_type=observation_type,
            )
            trajectories[active_index].turns.append(turn)
            trajectories[active_index].completed = completed
            if not done:
                next_active.append(active_index)
        active = next_active
    for trajectory in trajectories:
        trajectory.reward = search_r1_outcome_reward(trajectory)
    return trajectories


def _generate_responses(
    actor: Any,
    processor: Any,
    prompts: list[str],
    *,
    max_new_tokens: int,
    temperature: float,
    device: str,
    do_sample: bool,
) -> list[tuple[str, list[int]]]:
    import torch

    inputs = processor(text=prompts, padding=True, return_tensors="pt")
    inputs = {
        key: value.to(device) if hasattr(value, "to") else value
        for key, value in inputs.items()
    }
    prompt_length = int(inputs["input_ids"].shape[-1])
    generation_kwargs: dict[str, object] = {
        "max_new_tokens": max_new_tokens,
        "do_sample": do_sample,
        "use_cache": True,
        "pad_token_id": processor.tokenizer.pad_token_id,
        "eos_token_id": processor.tokenizer.eos_token_id,
    }
    if do_sample:
        generation_kwargs.update({"temperature": temperature, "top_p": 1.0})
    with torch.inference_mode():
        output_ids = actor.generate(**inputs, **generation_kwargs)
    generated: list[tuple[str, list[int]]] = []
    for output_row in output_ids:
        completion = output_row[prompt_length:]
        if processor.tokenizer.pad_token_id is not None:
            completion = completion[completion.ne(processor.tokenizer.pad_token_id)]
        response_ids = [int(item) for item in completion.detach().cpu().tolist()]
        raw = processor.tokenizer.decode(
            response_ids,
            skip_special_tokens=True,
        ).strip()
        bounded_raw = extract_first_json_object(raw)
        if bounded_raw != raw:
            response_ids = [
                int(item)
                for item in processor.tokenizer(
                    bounded_raw,
                    add_special_tokens=False,
                ).input_ids
            ]
            raw = bounded_raw
        generated.append((raw, response_ids))
    return generated


def _attach_old_and_reference_log_probs(
    actor: Any,
    reference: Any,
    processor: Any,
    turns: list[SearchR1Turn],
    *,
    temperature: float,
    device: str,
) -> None:
    actor.eval()
    reference.eval()
    for start in range(0, len(turns), 2):
        batch = turns[start : start + 2]
        old = _response_log_probs(
            actor,
            processor,
            batch,
            temperature=temperature,
            device=device,
            require_grad=False,
        )
        ref = _response_log_probs(
            reference,
            processor,
            batch,
            temperature=temperature,
            device=device,
            require_grad=False,
        )
        for turn, old_values, ref_values in zip(batch, old, ref, strict=True):
            turn.old_log_probs = [float(item) for item in old_values.cpu().tolist()]
            turn.reference_log_probs = [
                float(item) for item in ref_values.cpu().tolist()
            ]


def _grpo_update(
    actor: Any,
    optimizer: Any,
    processor: Any,
    turns: list[SearchR1Turn],
    *,
    temperature: float,
    clip_ratio: float,
    kl_loss_coef: float,
    device: str,
) -> dict[str, object]:
    import torch

    nonzero = [turn for turn in turns if abs(turn.advantage) > 1e-8]
    if not nonzero:
        return {
            "optimizer_step": False,
            "policy_loss": 0.0,
            "kl_loss": 0.0,
            "clip_fraction": 0.0,
            "gradient_norm": 0.0,
            "trainable_response_tokens": 0,
        }
    actor.train()
    actor.config.use_cache = False
    optimizer.zero_grad(set_to_none=True)
    total_tokens = sum(len(turn.response_token_ids) for turn in nonzero)
    policy_loss_sum = 0.0
    kl_loss_sum = 0.0
    clipped_tokens = 0
    for turn in nonzero:
        current = _response_log_probs(
            actor,
            processor,
            [turn],
            temperature=temperature,
            device=device,
            require_grad=True,
        )[0]
        old = torch.tensor(turn.old_log_probs, device=device, dtype=current.dtype)
        reference = torch.tensor(
            turn.reference_log_probs,
            device=device,
            dtype=current.dtype,
        )
        if not (len(current) == len(old) == len(reference)):
            raise RuntimeError("Search-R1 token log-probabilities are misaligned")
        advantage = torch.tensor(turn.advantage, device=device, dtype=current.dtype)
        log_ratio = current - old
        ratio = torch.exp(torch.clamp(log_ratio, min=-20.0, max=20.0))
        unclipped = -advantage * ratio
        clipped = -advantage * torch.clamp(
            ratio,
            1.0 - clip_ratio,
            1.0 + clip_ratio,
        )
        token_policy_loss = torch.maximum(unclipped, clipped)
        reference_delta = reference - current
        token_kl = torch.clamp(
            torch.exp(torch.clamp(reference_delta, max=20.0)) - reference_delta - 1.0,
            min=-10.0,
            max=10.0,
        )
        loss = (token_policy_loss.sum() + kl_loss_coef * token_kl.sum()) / total_tokens
        loss.backward()
        policy_loss_sum += float(token_policy_loss.detach().sum().cpu())
        kl_loss_sum += float(token_kl.detach().sum().cpu())
        clipped_tokens += int((clipped > unclipped).detach().sum().cpu())
    gradient_norm = torch.nn.utils.clip_grad_norm_(
        [parameter for parameter in actor.parameters() if parameter.requires_grad],
        max_norm=1.0,
    )
    optimizer.step()
    actor.eval()
    return {
        "optimizer_step": True,
        "policy_loss": round(policy_loss_sum / total_tokens, 8),
        "kl_loss": round(kl_loss_sum / total_tokens, 8),
        "clip_fraction": round(clipped_tokens / total_tokens, 8),
        "gradient_norm": round(float(gradient_norm.detach().cpu()), 8),
        "trainable_response_tokens": total_tokens,
    }


def _response_log_probs(
    model: Any,
    processor: Any,
    turns: list[SearchR1Turn],
    *,
    temperature: float,
    device: str,
    require_grad: bool,
) -> list[Any]:
    import torch

    tokenizer = processor.tokenizer
    encoded: list[tuple[list[int], list[int]]] = []
    for turn in turns:
        prompt_ids = tokenizer(
            turn.prompt,
            add_special_tokens=False,
        ).input_ids
        if len(prompt_ids) > 4_096:
            prompt_ids = prompt_ids[-4_096:]
        encoded.append((prompt_ids, turn.response_token_ids))
    max_length = max(len(prompt) + len(response) for prompt, response in encoded)
    input_ids = torch.full(
        (len(encoded), max_length),
        tokenizer.pad_token_id,
        dtype=torch.long,
        device=device,
    )
    attention_mask = torch.zeros_like(input_ids)
    response_positions: list[torch.Tensor] = []
    for row_index, (prompt_ids, response_ids) in enumerate(encoded):
        combined = [*prompt_ids, *response_ids]
        offset = max_length - len(combined)
        input_ids[row_index, offset:] = torch.tensor(
            combined,
            dtype=torch.long,
            device=device,
        )
        attention_mask[row_index, offset:] = 1
        response_positions.append(
            torch.arange(
                offset + len(prompt_ids),
                offset + len(combined),
                dtype=torch.long,
                device=device,
            )
        )
    context = torch.enable_grad() if require_grad else torch.inference_mode()
    with context:
        logits = model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            use_cache=False,
        ).logits
        results: list[Any] = []
        for row_index, positions in enumerate(response_positions):
            token_logits = logits[row_index, positions - 1, :].float() / temperature
            targets = input_ids[row_index, positions]
            selected = token_logits.gather(-1, targets.unsqueeze(-1)).squeeze(-1)
            results.append(selected - torch.logsumexp(token_logits, dim=-1))
    return results


def _render_prompt(processor: Any, state: DeepResearchState) -> str:
    return processor.apply_chat_template(
        build_research_decision_messages(state),
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )


def assign_group_outcome_advantages(group: list[SearchR1Trajectory]) -> None:
    rewards = [item.reward for item in group]
    mean = statistics.fmean(rewards)
    deviation = statistics.stdev(rewards) if len(rewards) > 1 else 0.0
    for trajectory in group:
        advantage = (
            0.0 if deviation < 1e-6 else (trajectory.reward - mean) / (deviation + 1e-6)
        )
        trajectory.advantage = advantage
        for turn in trajectory.turns:
            turn.advantage = advantage


def search_r1_outcome_reward(trajectory: SearchR1Trajectory) -> float:
    if trajectory.completed:
        return 1.0
    if trajectory.family == "sensitive_abort":
        return 0.0
    if trajectory.turns and all(
        turn.structured_output_valid for turn in trajectory.turns
    ):
        return 0.2
    if any(turn.structured_output_valid for turn in trajectory.turns):
        return 0.1
    return 0.0


def _stratified_training_selection(
    scenarios: list[WebRLPilotScenario],
    update_index: int,
) -> list[WebRLPilotScenario]:
    by_family: dict[str, list[WebRLPilotScenario]] = defaultdict(list)
    for scenario in scenarios:
        by_family[scenario.family].append(scenario)
    return [
        sorted(items, key=lambda item: item.scenario_id)[update_index % len(items)]
        for _family, items in sorted(by_family.items())
    ]


def _trajectory_artifact_row(
    trajectory: SearchR1Trajectory,
) -> dict[str, object]:
    return {
        "scenario_id": trajectory.scenario_id,
        "split": trajectory.split,
        "family": trajectory.family,
        "rollout_index": trajectory.rollout_index,
        "completed": trajectory.completed,
        "reward": trajectory.reward,
        "advantage": trajectory.advantage,
        "turns": [
            {
                **asdict(turn),
                "prompt": None,
                "prompt_hash": canonical_hash(turn.prompt),
                "state_tokens_masked": turn.prompt_tokens,
                "response_tokens_trainable": len(turn.response_token_ids),
            }
            for turn in trajectory.turns
        ],
    }


def _group_by_family(
    trajectories: list[SearchR1Trajectory],
) -> dict[str, list[SearchR1Trajectory]]:
    grouped: dict[str, list[SearchR1Trajectory]] = defaultdict(list)
    for trajectory in trajectories:
        grouped[trajectory.family].append(trajectory)
    return dict(sorted(grouped.items()))


def _load_base_model(model_class: Any, model_path: Path, device: str) -> Any:
    import torch

    return model_class.from_pretrained(
        model_path,
        dtype=torch.bfloat16,
        trust_remote_code=True,
        local_files_only=True,
        low_cpu_mem_usage=True,
    ).to(device)


def _validate_config(
    *,
    model_path: Path,
    adapter_path: Path,
    output_dir: Path,
    updates: int,
    group_size: int,
    max_turns: int,
    max_new_tokens: int,
    temperature: float,
    learning_rate: float,
    clip_ratio: float,
    kl_loss_coef: float,
) -> None:
    if not model_path.is_dir() or not adapter_path.is_dir():
        raise FileNotFoundError("Search-R1 Pilot requires local model and SFT adapter")
    if output_dir.exists():
        raise FileExistsError(output_dir)
    if updates <= 0 or group_size < 2 or max_turns <= 0 or max_new_tokens <= 0:
        raise ValueError("invalid Search-R1 Pilot rollout configuration")
    if temperature <= 0 or not 0 < learning_rate < 1e-3:
        raise ValueError("invalid Search-R1 Pilot optimization configuration")
    if not 0 < clip_ratio < 1 or not 0 <= kl_loss_coef <= 1:
        raise ValueError("invalid Search-R1 Pilot PPO/KL configuration")


def _assert_offline() -> None:
    active = [name for name in FORBIDDEN_ENDPOINT_VARS if os.getenv(name)]
    if active:
        raise RuntimeError(f"Search-R1 Pilot refuses configured endpoints: {active}")
    if os.getenv("HF_HUB_OFFLINE") != "1" or os.getenv("TRANSFORMERS_OFFLINE") != "1":
        raise RuntimeError("Search-R1 Pilot requires local-only model mode")


def _rate(values: Any) -> float:
    items = list(values)
    return round(sum(bool(item) for item in items) / len(items), 6) if items else 0.0


def _mean(values: Any) -> float:
    items = [float(item) for item in values]
    return round(sum(items) / len(items), 6) if items else 0.0


def _population_std(values: Any) -> float:
    items = [float(item) for item in values]
    if not items:
        return 0.0
    mean = sum(items) / len(items)
    return round(math.sqrt(sum((item - mean) ** 2 for item in items) / len(items)), 6)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--sft-adapter", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=7703)
    parser.add_argument("--updates", type=int, default=1)
    parser.add_argument("--group-size", type=int, default=5)
    parser.add_argument("--max-turns", type=int, default=4)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--learning-rate", type=float, default=5e-7)
    parser.add_argument("--clip-ratio", type=float, default=0.2)
    parser.add_argument("--kl-loss-coef", type=float, default=0.001)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--eval-only-split", choices=("validation", "test"))
    args = parser.parse_args()
    if args.eval_only_split is not None:
        summary = evaluate_search_r1_adapter(
            model_path=args.model.resolve(),
            adapter_path=args.sft_adapter.resolve(),
            output_dir=args.output_dir.resolve(),
            split=args.eval_only_split,
            max_turns=args.max_turns,
            max_new_tokens=args.max_new_tokens,
            device=args.device,
        )
    else:
        summary = run_search_r1_grpo_pilot(
            model_path=args.model.resolve(),
            sft_adapter_path=args.sft_adapter.resolve(),
            output_dir=args.output_dir.resolve(),
            seed=args.seed,
            updates=args.updates,
            group_size=args.group_size,
            max_turns=args.max_turns,
            max_new_tokens=args.max_new_tokens,
            temperature=args.temperature,
            learning_rate=args.learning_rate,
            clip_ratio=args.clip_ratio,
            kl_loss_coef=args.kl_loss_coef,
            device=args.device,
        )
    print(canonical_json(summary))


if __name__ == "__main__":
    main()


__all__ = [
    "SEARCH_R1_REFERENCE_COMMIT",
    "SearchR1Trajectory",
    "SearchR1Turn",
    "assign_group_outcome_advantages",
    "evaluate_search_r1_adapter",
    "run_search_r1_grpo_pilot",
    "search_r1_outcome_reward",
]
