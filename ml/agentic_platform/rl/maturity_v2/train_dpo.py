"""Constrained-token DPO baseline for Router RL maturity v2 comparisons."""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
import random
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..spec import canonical_json, sha256_file
from .actions import RouterActionSpace, build_action_space
from .policy import (
    action_entropy,
    available_action_log_probs,
    create_lora_policy,
    decision_prompt,
    encode_prompts,
    final_token_logits,
    load_processor,
    trainable_parameter_count,
)
from .reference_cache import load_reference_cache
from .spec import MaturityRouterState, load_maturity_states

SCHEMA_VERSION = "studyhub.agent.router_rl.dpo_config.v2"
ALGORITHM = "constrained_token_dpo_baseline_v2"
FORBIDDEN_ENDPOINT_VARS = (
    "DATABASE_URL",
    "MYSQL_URL",
    "STUDYHUB_DATABASE_URL",
    "OPENAI_BASE_URL",
    "ANTHROPIC_BASE_URL",
    "STUDYHUB_AGENTIC_MODEL_BASE_URL",
)


@dataclass(frozen=True, slots=True)
class DPOConfig:
    model_path: Path
    train_path: Path
    reference_cache_path: Path
    output_dir: Path
    lora_rank: int
    lora_alpha: int
    lora_dropout: float
    updates: int
    states_per_update: int
    learning_rate: float
    beta: float
    max_grad_norm: float
    max_prompt_tokens: int
    gradient_checkpointing: bool
    device: str
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> DPOConfig:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != SCHEMA_VERSION or raw.get("algorithm") != ALGORITHM:
            raise ValueError("unsupported DPO config")
        isolation = raw.get("isolation") or {}
        if any(
            isolation.get(name) is not False
            for name in (
                "production_access_allowed",
                "paid_material_allowed",
                "test_read_allowed",
                "sealed_read_allowed",
                "production_final_holdout_allowed",
            )
        ):
            raise ValueError("DPO config violates the isolation contract")
        config = cls(
            model_path=Path(raw["model_path"]).resolve(),
            train_path=Path(raw["train_path"]).resolve(),
            reference_cache_path=Path(raw["reference_cache_path"]).resolve(),
            output_dir=Path(raw["output_dir"]).resolve(),
            lora_rank=int(raw["lora_rank"]),
            lora_alpha=int(raw.get("lora_alpha") or int(raw["lora_rank"]) * 2),
            lora_dropout=float(raw.get("lora_dropout", 0.0)),
            updates=int(raw["updates"]),
            states_per_update=int(raw["states_per_update"]),
            learning_rate=float(raw["learning_rate"]),
            beta=float(raw["beta"]),
            max_grad_norm=float(raw.get("max_grad_norm", 1.0)),
            max_prompt_tokens=int(raw.get("max_prompt_tokens", 4096)),
            gradient_checkpointing=raw.get("gradient_checkpointing") is True,
            device=str(raw.get("device", "cuda:0")),
            raw=raw,
        )
        config.validate()
        return config

    def validate(self) -> None:
        for path in (self.model_path, self.train_path, self.reference_cache_path):
            if not path.exists():
                raise FileNotFoundError(path)
        if self.lora_rank not in {8, 16, 32}:
            raise ValueError("DPO LoRA rank must be preregistered")
        if self.updates < 1 or self.states_per_update < 1:
            raise ValueError("DPO update counts must be positive")
        if not 0 < self.learning_rate < 1e-3 or not 0 < self.beta <= 1:
            raise ValueError("DPO learning rate or beta is invalid")


@dataclass(frozen=True, slots=True)
class Preference:
    state: MaturityRouterState
    space: RouterActionSpace
    chosen_index: int
    rejected_index: int
    reference_chosen_log_prob: float
    reference_rejected_log_prob: float


def train_dpo(*, config_path: Path, seed: int) -> dict[str, Any]:
    _assert_offline_environment()
    config = DPOConfig.load(config_path)
    if config.output_dir.exists() and any(config.output_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite DPO output: {config.output_dir}")
    config.output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(config.output_dir / "config.snapshot.json", config.raw)
    states = load_maturity_states(config.train_path, splits={"train"})
    references = load_reference_cache(config.reference_cache_path)
    preferences = _build_preferences(states, references)
    schedule = _preference_schedule(
        preferences,
        updates=config.updates,
        states_per_update=config.states_per_update,
        seed=seed,
    )

    import torch
    from torch.nn import functional
    from transformers.utils import logging as transformers_logging

    transformers_logging.set_verbosity_error()
    transformers_logging.disable_progress_bar()
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    processor = load_processor(config.model_path)
    policy = create_lora_policy(
        config.model_path,
        device=config.device,
        rank=config.lora_rank,
        alpha=config.lora_alpha,
        dropout=config.lora_dropout,
        gradient_checkpointing=config.gradient_checkpointing,
    )
    policy.eval()
    optimizer = torch.optim.AdamW(
        (parameter for parameter in policy.parameters() if parameter.requires_grad),
        lr=config.learning_rate,
        betas=(0.9, 0.95),
    )
    metrics_path = config.output_dir / "trainer_metrics.jsonl"
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    for update_index, preference_batch in enumerate(schedule, start=1):
        optimizer.zero_grad(set_to_none=True)
        losses: list[float] = []
        margins: list[float] = []
        accuracies: list[bool] = []
        entropies: list[float] = []
        for preference in preference_batch:
            prompt = decision_prompt(processor, preference.state, preference.space)
            encoded = encode_prompts(
                processor,
                [prompt],
                device=config.device,
                max_prompt_tokens=config.max_prompt_tokens,
            )
            full_logits = final_token_logits(policy, encoded)[0]
            log_probs = available_action_log_probs(
                full_logits,
                space=preference.space,
                tokenizer=processor.tokenizer,
                temperature=1.0,
            )
            chosen = log_probs[preference.chosen_index]
            rejected = log_probs[preference.rejected_index]
            policy_margin = chosen - rejected
            reference_margin = (
                preference.reference_chosen_log_prob
                - preference.reference_rejected_log_prob
            )
            logit = config.beta * (policy_margin - reference_margin)
            loss = -functional.logsigmoid(logit) / len(preference_batch)
            loss.backward()
            losses.append(float(loss.detach().item()) * len(preference_batch))
            margins.append(float(policy_margin.detach().item()))
            accuracies.append(bool(policy_margin.detach().item() > 0))
            entropies.append(float(action_entropy(log_probs).detach().item()))
        grad_norm = torch.nn.utils.clip_grad_norm_(
            [parameter for parameter in policy.parameters() if parameter.requires_grad],
            config.max_grad_norm,
        )
        optimizer.step()
        row = {
            "update": update_index,
            "loss": round(sum(losses) / len(losses), 8),
            "chosen_rejected_margin": round(sum(margins) / len(margins), 8),
            "preference_accuracy": round(sum(accuracies) / len(accuracies), 6),
            "action_entropy": round(sum(entropies) / len(entropies), 8),
            "grad_norm": round(float(grad_norm.detach().item()), 8),
            "cuda_memory_peak_mib": round(torch.cuda.max_memory_allocated() / (1024**2), 3),
        }
        rows.append(row)
        _append_jsonl(metrics_path, row)
        if update_index % 25 == 0 or update_index == config.updates:
            print(canonical_json(row), flush=True)
    adapter_dir = config.output_dir / "adapter"
    policy.save_pretrained(adapter_dir, safe_serialization=True)
    duration = time.perf_counter() - started
    summary = {
        "schema_version": "studyhub.agent.router_rl.dpo_run.v2",
        "algorithm": ALGORITHM,
        "seed": seed,
        "training_succeeded": True,
        "updates": config.updates,
        "preference_pairs_seen": config.updates * config.states_per_update,
        "unique_preference_pairs": len(preferences),
        "duration_seconds": round(duration, 3),
        "final_loss": rows[-1]["loss"],
        "final_preference_accuracy": rows[-1]["preference_accuracy"],
        "mean_preference_accuracy": round(
            sum(row["preference_accuracy"] for row in rows) / len(rows),
            6,
        ),
        "finite_metrics": all(
            math.isfinite(float(row[key]))
            for row in rows
            for key in ("loss", "chosen_rejected_margin", "action_entropy", "grad_norm")
        ),
        "lora": {
            "rank": config.lora_rank,
            "alpha": config.lora_alpha,
            "trainable_parameters": trainable_parameter_count(policy),
        },
        "gpu": {
            "name": torch.cuda.get_device_name(),
            "peak_memory_mib": round(torch.cuda.max_memory_allocated() / (1024**2), 3),
        },
        "artifacts": {
            "adapter_path": str(adapter_dir.resolve()),
            "adapter_sha256": sha256_file(adapter_dir / "adapter_model.safetensors"),
            "metrics_sha256": sha256_file(metrics_path),
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
    summary_path = config.output_dir / "run_summary.json"
    _write_json(summary_path, summary)
    _write_json(
        config.output_dir / "run_manifest.json",
        {
            "schema_version": "studyhub.agent.router_rl.dpo_manifest.v2",
            "git_commit": subprocess.check_output(
                ["git", "-C", str(Path(__file__).resolve().parents[4]), "rev-parse", "HEAD"],
                text=True,
            ).strip(),
            "config_sha256": sha256_file(config.output_dir / "config.snapshot.json"),
            "train_sha256": sha256_file(config.train_path),
            "reference_cache_sha256": sha256_file(config.reference_cache_path),
            "implementation_sha256": sha256_file(Path(__file__)),
            "summary_sha256": sha256_file(summary_path),
            "production_access": False,
            "test_read": False,
            "sealed_read": False,
        },
    )
    del policy, optimizer
    gc.collect()
    torch.cuda.empty_cache()
    return summary


def _build_preferences(
    states: list[MaturityRouterState],
    references: dict[str, dict[str, Any]],
) -> list[Preference]:
    result: list[Preference] = []
    for state in states:
        space = build_action_space(state)
        if len(space.candidates) < 2:
            continue
        reference = references.get(state.state_id)
        if reference is None or list(reference["routes"]) != list(space.routes):
            raise ValueError(f"missing or mismatched DPO reference for {state.state_id}")
        chosen = space.routes.index(space.oracle_route)
        rejected = max(
            (index for index in range(len(space.routes)) if index != chosen),
            key=lambda index: float(reference["log_probs"][index]),
        )
        result.append(
            Preference(
                state=state,
                space=space,
                chosen_index=chosen,
                rejected_index=rejected,
                reference_chosen_log_prob=float(reference["log_probs"][chosen]),
                reference_rejected_log_prob=float(reference["log_probs"][rejected]),
            )
        )
    if len(result) < 1_000:
        raise ValueError(f"insufficient DPO preference pairs: {len(result)}")
    return result


def _preference_schedule(
    preferences: list[Preference],
    *,
    updates: int,
    states_per_update: int,
    seed: int,
) -> list[list[Preference]]:
    rng = random.Random(seed)
    stream: list[Preference] = []
    required = updates * states_per_update
    while len(stream) < required:
        cycle = list(preferences)
        rng.shuffle(cycle)
        stream.extend(cycle)
    return [
        stream[start : start + states_per_update]
        for start in range(0, required, states_per_update)
    ]


def _append_jsonl(path: Path, value: object) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_json(value) + "\n")


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _assert_offline_environment() -> None:
    active = [name for name in FORBIDDEN_ENDPOINT_VARS if os.getenv(name)]
    if active:
        raise RuntimeError(f"offline DPO refuses configured endpoints: {active}")
    if os.getenv("HF_HUB_OFFLINE") != "1" or os.getenv("TRANSFORMERS_OFFLINE") != "1":
        raise RuntimeError("offline DPO requires local-only Hugging Face mode")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=26081201)
    args = parser.parse_args()
    result = train_dpo(config_path=args.config.resolve(), seed=args.seed)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
