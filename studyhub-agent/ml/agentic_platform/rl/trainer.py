"""Small, auditable GRPO-style policy-gradient pilot for the StudyHub Router.

This is intentionally not presented as TRL/veRL GRPO. It implements the
group-relative clipped objective directly so old-policy log probabilities,
reference KL, rewards, and gradients remain inspectable in one offline job.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import random
import subprocess
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .reward import RouterRewardPolicy, group_relative_advantages, score_double_ledger
from .spec import RouterRLState, canonical_json, load_states, sha256_file

ROOT = Path(__file__).resolve().parents[3]
FORBIDDEN_ENDPOINT_VARS = (
    "DATABASE_URL",
    "MYSQL_URL",
    "STUDYHUB_DATABASE_URL",
    "OPENAI_BASE_URL",
    "ANTHROPIC_BASE_URL",
    "STUDYHUB_AGENTIC_MODEL_BASE_URL",
)


@dataclass(frozen=True, slots=True)
class TrainConfig:
    model_path: Path
    adapter_path: Path
    dataset_path: Path
    input_lock_path: Path
    output_root: Path
    train_states: int
    group_size: int
    max_new_tokens: int
    temperature: float
    top_p: float
    learning_rate: float
    adam_beta1: float
    adam_beta2: float
    weight_decay: float
    kl_beta: float
    clip_epsilon: float
    max_grad_norm: float
    checkpoint_every: int
    success_threshold: float
    device: str
    gradient_checkpointing: bool
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> TrainConfig:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != "studyhub.agent.router_rl.train_config.v1":
            raise ValueError("unsupported RL training config")
        if raw.get("algorithm") != "group_relative_policy_optimization_contextual_bandit_v1":
            raise ValueError("unsupported RL algorithm")
        if raw.get("production_access_allowed") is not False or raw.get("final_holdout_allowed") is not False:
            raise ValueError("RL pilot must disable production and final holdout access")
        config = cls(
            model_path=Path(raw["model_path"]).resolve(),
            adapter_path=Path(raw["sft_adapter_path"]).resolve(),
            dataset_path=Path(raw["dataset_path"]).resolve(),
            input_lock_path=Path(raw["input_lock_path"]).resolve(),
            output_root=Path(raw["output_root"]).resolve(),
            train_states=int(raw["train_states"]),
            group_size=int(raw["group_size"]),
            max_new_tokens=int(raw["max_new_tokens"]),
            temperature=float(raw["temperature"]),
            top_p=float(raw["top_p"]),
            learning_rate=float(raw["learning_rate"]),
            adam_beta1=float(raw["adam_beta1"]),
            adam_beta2=float(raw["adam_beta2"]),
            weight_decay=float(raw["weight_decay"]),
            kl_beta=float(raw["kl_beta"]),
            clip_epsilon=float(raw["clip_epsilon"]),
            max_grad_norm=float(raw["max_grad_norm"]),
            checkpoint_every=int(raw["checkpoint_every"]),
            success_threshold=float(raw["success_threshold"]),
            device=str(raw["device"]),
            gradient_checkpointing=raw.get("gradient_checkpointing") is True,
            raw=raw,
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.group_size < 2 or self.train_states < 1 or self.max_new_tokens < 32:
            raise ValueError("invalid group size, train state count, or decode budget")
        if not 0 < self.temperature <= 2 or not 0 < self.top_p <= 1:
            raise ValueError("sampling parameters are outside the supported range")
        if not 0 < self.learning_rate < 1e-3 or not 0 <= self.kl_beta <= 1:
            raise ValueError("optimizer or KL configuration is unsafe")
        for path in (self.model_path, self.adapter_path):
            if not path.is_dir():
                raise FileNotFoundError(path)
        for path in (self.dataset_path, self.input_lock_path):
            if not path.is_file():
                raise FileNotFoundError(path)


def train(*, config_path: Path, seed: int, output_dir: Path | None = None) -> dict[str, Any]:
    _assert_offline_environment()
    config = TrainConfig.load(config_path)
    _verify_input_lock(config, config_path)
    run_dir = output_dir.resolve() if output_dir else config.output_root / f"seed_{seed}"
    if any((run_dir / name).exists() for name in ("run_summary.json", "trainer_metrics.jsonl", "rollout_samples.jsonl", "adapter")):
        raise FileExistsError(f"RL run is already finalized: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    _seed_everything(seed)
    states = _select_training_states(load_states(config.dataset_path, splits={"train"}), count=config.train_states, seed=seed)
    _write_json(run_dir / "selected_states.json", {"seed": seed, "state_ids": [state.state_id for state in states]})
    _write_json(run_dir / "config.snapshot.json", config.raw)

    import torch
    from peft import PeftModel
    from torch.nn import functional
    from transformers import AutoModelForMultimodalLM, AutoProcessor
    from transformers.utils import logging as transformers_logging

    transformers_logging.set_verbosity_error()
    transformers_logging.disable_progress_bar()
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    processor = AutoProcessor.from_pretrained(config.model_path, trust_remote_code=True, local_files_only=True)
    processor.tokenizer.padding_side = "left"

    def load_model(*, trainable: bool):
        base = AutoModelForMultimodalLM.from_pretrained(
            config.model_path,
            dtype=torch.bfloat16,
            trust_remote_code=True,
            local_files_only=True,
            low_cpu_mem_usage=True,
        ).to(config.device)
        model = PeftModel.from_pretrained(base, config.adapter_path, is_trainable=trainable)
        model.eval()
        if trainable and config.gradient_checkpointing:
            model.gradient_checkpointing_enable()
        return model

    policy = load_model(trainable=True)
    reference = load_model(trainable=False)
    for parameter in reference.parameters():
        parameter.requires_grad_(False)
    optimizer = torch.optim.AdamW(
        (parameter for parameter in policy.parameters() if parameter.requires_grad),
        lr=config.learning_rate,
        betas=(config.adam_beta1, config.adam_beta2),
        weight_decay=config.weight_decay,
    )
    trainable_parameters = sum(parameter.numel() for parameter in policy.parameters() if parameter.requires_grad)
    reward_policy = RouterRewardPolicy()
    metrics_path = run_dir / "trainer_metrics.jsonl"
    samples_path = run_dir / "rollout_samples.jsonl"
    family_rewards: dict[str, list[float]] = defaultdict(list)
    hacking_counts: Counter[str] = Counter()
    correction_counts: Counter[str] = Counter()
    update_rows: list[dict[str, Any]] = []
    generated_tokens = 0

    for update_index, state in enumerate(states, start=1):
        prompt = processor.apply_chat_template(
            list(state.messages),
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        encoded = processor(text=[prompt] * config.group_size, padding=True, return_tensors="pt")
        encoded = {key: value.to(config.device) if hasattr(value, "to") else value for key, value in encoded.items()}
        prompt_length = int(encoded["input_ids"].shape[1])
        policy.eval()
        with torch.no_grad():
            generated = policy.generate(
                **encoded,
                max_new_tokens=config.max_new_tokens,
                do_sample=True,
                temperature=config.temperature,
                top_p=config.top_p,
                use_cache=True,
                pad_token_id=processor.tokenizer.pad_token_id,
                eos_token_id=processor.tokenizer.eos_token_id,
            )
        completion_ids = generated[:, prompt_length:]
        completion_mask = _completion_mask(completion_ids, processor.tokenizer.pad_token_id, processor.tokenizer.eos_token_id)
        texts = [
            processor.tokenizer.decode(row[mask].detach().cpu(), skip_special_tokens=True).strip()
            for row, mask in zip(completion_ids, completion_mask, strict=True)
        ]
        ledgers = [score_double_ledger(text, state, reward_policy=reward_policy) for text in texts]
        rewards = [ledger.raw.policy_reward for ledger in ledgers]
        advantages = torch.tensor(group_relative_advantages(rewards), dtype=torch.float32, device=config.device)
        generated_tokens += int(completion_mask.sum().item())
        attention_mask = generated.ne(processor.tokenizer.pad_token_id).long()
        with torch.no_grad():
            old_logprobs = _completion_logprobs(policy, generated, attention_mask, completion_mask, prompt_length, functional)
            reference_logprobs = _completion_logprobs(reference, generated, attention_mask, completion_mask, prompt_length, functional)

        optimizer.zero_grad(set_to_none=True)
        current_logprobs = _completion_logprobs(policy, generated, attention_mask, completion_mask, prompt_length, functional)
        log_ratio = (current_logprobs - old_logprobs).clamp(-8, 8)
        ratio = log_ratio.exp()
        unclipped = ratio * advantages
        clipped = ratio.clamp(1 - config.clip_epsilon, 1 + config.clip_epsilon) * advantages
        policy_loss = -torch.minimum(unclipped, clipped).mean()
        delta = (reference_logprobs - current_logprobs).clamp(-8, 8)
        kl = (delta.exp() - delta - 1).mean()
        loss = policy_loss + config.kl_beta * kl
        loss.backward()
        grad_norm = torch.nn.utils.clip_grad_norm_(
            [parameter for parameter in policy.parameters() if parameter.requires_grad],
            config.max_grad_norm,
        )
        optimizer.step()

        clip_fraction = ((ratio < 1 - config.clip_epsilon) | (ratio > 1 + config.clip_epsilon)).float().mean()
        entropy_proxy = -current_logprobs.detach().mean()
        row = {
            "update": update_index,
            "state_id": state.state_id,
            "family": state.family,
            "reward_mean": round(sum(rewards) / len(rewards), 6),
            "reward_min": min(rewards),
            "reward_max": max(rewards),
            "reward_std": round(float(torch.tensor(rewards).std(unbiased=False).item()), 6),
            "nonzero_advantage": any(abs(value) > 1e-6 for value in advantages.tolist()),
            "policy_loss": round(float(policy_loss.detach().item()), 8),
            "total_loss": round(float(loss.detach().item()), 8),
            "kl": round(float(kl.detach().item()), 8),
            "entropy_proxy": round(float(entropy_proxy.item()), 8),
            "clip_fraction": round(float(clip_fraction.item()), 8),
            "grad_norm": round(float(grad_norm.item()), 8),
            "completion_tokens_mean": round(float(completion_mask.sum(dim=1).float().mean().item()), 3),
            "learning_rate": optimizer.param_groups[0]["lr"],
            "cuda_memory_allocated_mib": round(torch.cuda.memory_allocated() / (1024**2), 3),
            "cuda_memory_peak_mib": round(torch.cuda.max_memory_allocated() / (1024**2), 3),
        }
        update_rows.append(row)
        _append_jsonl(metrics_path, row)
        for group_index, (text, reward, advantage, ledger) in enumerate(zip(texts, rewards, advantages.tolist(), ledgers, strict=True)):
            family_rewards[state.family].append(reward)
            hacking_counts.update(ledger.raw.reward_hacking_flags)
            correction_counts.update(ledger.constraint_corrections)
            _append_jsonl(
                samples_path,
                {
                    "update": update_index,
                    "group_index": group_index,
                    "state_id": state.state_id,
                    "family": state.family,
                    "raw_generated": text,
                    "reward": reward,
                    "advantage": round(float(advantage), 8),
                    "double_ledger": ledger.to_dict(),
                },
            )
        print(canonical_json(row), flush=True)
        if update_index % config.checkpoint_every == 0:
            policy.save_pretrained(run_dir / "checkpoints" / f"update_{update_index:03d}", safe_serialization=True)

    adapter_dir = run_dir / "adapter"
    policy.save_pretrained(adapter_dir, safe_serialization=True)
    duration = time.perf_counter() - started
    summary = {
        "schema_version": "studyhub.agent.router_rl.train_run.v1",
        "algorithm": config.raw["algorithm"],
        "seed": seed,
        "training_succeeded": True,
        "duration_seconds": round(duration, 3),
        "states": len(states),
        "rollouts": len(states) * config.group_size,
        "group_size": config.group_size,
        "generated_tokens": generated_tokens,
        "trainable_parameters": trainable_parameters,
        "optimizer": "AdamW",
        "objective": {
            "group_relative_advantage": True,
            "clipped_policy_ratio": True,
            "reference_kl_beta": config.kl_beta,
            "deterministic_constraints_rewarded": False,
            "reward_ledger_used_for_gradient": "raw_policy_proposal",
            "executable_ledger_used_for_gradient": False,
        },
        "reward": {
            "mean": round(sum(row["reward_mean"] for row in update_rows) / len(update_rows), 6),
            "families": {family: round(sum(values) / len(values), 6) for family, values in sorted(family_rewards.items())},
        },
        "stability": {
            "final_policy_loss": update_rows[-1]["policy_loss"],
            "mean_kl": round(sum(row["kl"] for row in update_rows) / len(update_rows), 8),
            "max_kl": max(row["kl"] for row in update_rows),
            "mean_entropy_proxy": round(sum(row["entropy_proxy"] for row in update_rows) / len(update_rows), 8),
            "mean_clip_fraction": round(sum(row["clip_fraction"] for row in update_rows) / len(update_rows), 8),
            "max_grad_norm": max(row["grad_norm"] for row in update_rows),
            "mean_completion_tokens": round(sum(row["completion_tokens_mean"] for row in update_rows) / len(update_rows), 3),
        },
        "reward_hacking_flags": dict(sorted(hacking_counts.items())),
        "constraint_corrections": dict(sorted(correction_counts.items())),
        "gpu": {
            "device": config.device,
            "name": torch.cuda.get_device_name(),
            "peak_memory_mib": round(torch.cuda.max_memory_allocated() / (1024**2), 3),
        },
        "artifacts": {
            "adapter_path": str(adapter_dir.resolve()),
            "adapter_sha256": sha256_file(adapter_dir / "adapter_model.safetensors"),
            "metrics_path": str(metrics_path.resolve()),
            "metrics_sha256": sha256_file(metrics_path),
            "samples_path": str(samples_path.resolve()),
            "samples_sha256": sha256_file(samples_path),
        },
        "isolation": {
            "production_api_called": False,
            "production_database_accessed": False,
            "production_oss_write_called": False,
            "paid_material_used": False,
            "development_diagnostic_read": False,
            "final_holdout_read": False,
        },
    }
    _write_json(run_dir / "run_summary.json", summary)
    _write_json(
        run_dir / "run_manifest.json",
        {
            "schema_version": "studyhub.agent.router_rl.run_manifest.v1",
            "git_commit": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
            "config_path": str(config_path.resolve()),
            "config_sha256": sha256_file(config_path),
            "input_lock_path": str(config.input_lock_path),
            "input_lock_sha256": sha256_file(config.input_lock_path),
            "dataset_sha256": sha256_file(config.dataset_path),
            "seed": seed,
            "implementation_sha256": sha256_file(Path(__file__)),
            "summary_sha256": sha256_file(run_dir / "run_summary.json"),
        },
    )
    del reference, policy, optimizer
    gc.collect()
    torch.cuda.empty_cache()
    return summary


def _completion_logprobs(model, sequence_ids, attention_mask, completion_mask, prompt_length, functional):
    outputs = model(input_ids=sequence_ids, attention_mask=attention_mask, use_cache=False)
    logits = outputs.logits[:, prompt_length - 1 : -1, :].float()
    targets = sequence_ids[:, prompt_length:]
    token_logprobs = -functional.cross_entropy(logits.transpose(1, 2), targets, reduction="none")
    mask = completion_mask.to(token_logprobs.dtype)
    return (token_logprobs * mask).sum(dim=1) / mask.sum(dim=1).clamp_min(1)


def _completion_mask(completion_ids, pad_token_id: int | None, eos_token_id: int | None):
    import torch

    mask = torch.ones_like(completion_ids, dtype=torch.bool)
    if pad_token_id is not None and pad_token_id != eos_token_id:
        mask &= completion_ids.ne(pad_token_id)
    if eos_token_id is not None:
        eos = completion_ids.eq(eos_token_id)
        seen = eos.cumsum(dim=1)
        mask &= seen.le(1)
    return mask


def _select_training_states(states: list[RouterRLState], *, count: int, seed: int) -> list[RouterRLState]:
    eligible = [state for state in states if state.training_eligible and state.training_export_allowed]
    by_family: dict[str, list[RouterRLState]] = defaultdict(list)
    rng = random.Random(seed)
    for state in eligible:
        by_family[state.family].append(state)
    for values in by_family.values():
        rng.shuffle(values)
    selected: list[RouterRLState] = []
    while len(selected) < count:
        added = False
        for family in sorted(by_family):
            values = by_family[family]
            if values:
                selected.append(values.pop())
                added = True
                if len(selected) == count:
                    break
        if not added:
            break
    if len(selected) != count:
        raise ValueError(f"requested {count} train states but selected {len(selected)}")
    return selected


def _assert_offline_environment() -> None:
    active = [name for name in FORBIDDEN_ENDPOINT_VARS if os.getenv(name)]
    if active:
        raise RuntimeError(f"offline RL refuses configured production/model endpoints: {active}")
    if os.getenv("HF_HUB_OFFLINE") != "1" or os.getenv("TRANSFORMERS_OFFLINE") != "1":
        raise RuntimeError("offline RL requires HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1")


def _verify_input_lock(config: TrainConfig, config_path: Path) -> None:
    lock = json.loads(config.input_lock_path.read_text(encoding="utf-8"))
    checks = {
        "config": (str(lock.get("config", {}).get("sha256") or ""), sha256_file(config_path)),
        "dataset": (str(lock.get("dataset", {}).get("sha256") or ""), sha256_file(config.dataset_path)),
        "adapter": (
            str(lock.get("policy", {}).get("sft_adapter_sha256") or ""),
            sha256_file(config.adapter_path / "adapter_model.safetensors"),
        ),
    }
    mismatches = [name for name, (locked, actual) in checks.items() if locked != actual]
    if mismatches:
        raise RuntimeError(f"RL input lock mismatch: {mismatches}")
    isolation = lock.get("isolation") or {}
    if any(isolation.get(name) is not False for name in ("production_api_called", "production_database_accessed", "paid_material_used", "final_holdout_read")):
        raise RuntimeError("RL input lock does not prove offline isolation")


def _seed_everything(seed: int) -> None:
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    import torch

    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def _append_jsonl(path: Path, value: object) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_json(value) + "\n")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    summary = train(config_path=args.config.resolve(), seed=args.seed, output_dir=args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
