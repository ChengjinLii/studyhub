"""Evaluate constrained-token Router policies on locked maturity v2 splits."""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ..reward import score_double_ledger
from ..spec import canonical_json, sha256_file
from .actions import build_action_space
from .policy import (
    action_entropy,
    available_action_log_probs,
    decision_prompt,
    encode_prompts,
    final_token_logits,
    load_base_policy,
    load_lora_policy,
    load_processor,
    true_token_entropy,
)
from .spec import MaturityRouterState, load_maturity_states

FORBIDDEN_ENDPOINT_VARS = (
    "DATABASE_URL",
    "MYSQL_URL",
    "STUDYHUB_DATABASE_URL",
    "OPENAI_BASE_URL",
    "ANTHROPIC_BASE_URL",
    "STUDYHUB_AGENTIC_MODEL_BASE_URL",
)
CORRECTION_SEVERITY = {
    "recover_invalid_json": 3,
    "replace_unparseable_output": 3,
    "replace_unexecutable_action": 3,
    "select_safe_state_fallback": 3,
    "enforce_permission_boundary": 2,
    "force_final_budget": 2,
    "protect_explicit_page_route": 2,
    "honor_explicit_candidate_inspection": 2,
    "honor_explicit_evidence_read": 2,
    "honor_explicit_memory_read": 2,
    "honor_explicit_search": 2,
    "honor_explicit_synthesis": 2,
    "honor_explicit_final": 2,
    "recover_empty_search": 2,
    "safe_untrusted_continuation": 2,
    "protect_material_ids": 1,
    "protect_page_numbers": 1,
    "protect_search_limit": 1,
    "canonicalize_contract": 1,
}


def evaluate_policy(
    *,
    model_path: Path,
    adapter_path: Path | None,
    dataset_path: Path,
    split: str,
    output_dir: Path,
    device: str,
    max_prompt_tokens: int,
    action_temperature: float,
    seed: int,
    allow_test: bool = False,
    allow_sealed: bool = False,
) -> dict[str, Any]:
    _assert_offline_environment()
    if split == "test" and not allow_test:
        raise ValueError("test split requires an explicit frozen-candidate authorization")
    if split == "sealed" and not allow_sealed:
        raise ValueError("sealed split requires an explicit post-test authorization")
    if split not in {"validation", "test", "sealed"}:
        raise ValueError("evaluation supports only validation, test and sealed")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite evaluation output: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    states = load_maturity_states(
        dataset_path,
        splits={split},
        allow_sealed=allow_sealed,
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
    processor = load_processor(model_path)
    if adapter_path is None:
        policy = load_base_policy(model_path, device=device, trainable=False)
    else:
        policy = load_lora_policy(
            model_path,
            adapter_path,
            device=device,
            trainable=False,
        )
    policy.eval()
    rows: list[dict[str, Any]] = []
    with torch.no_grad():
        for index, state in enumerate(states, start=1):
            space = build_action_space(state)
            prompt = decision_prompt(processor, state, space)
            encoded = encode_prompts(
                processor,
                [prompt],
                device=device,
                max_prompt_tokens=max_prompt_tokens,
            )
            full_logits = final_token_logits(policy, encoded)[0]
            log_probs = available_action_log_probs(
                full_logits,
                space=space,
                tokenizer=processor.tokenizer,
                temperature=action_temperature,
            )
            selected_index = int(log_probs.argmax().item())
            selected = space.candidates[selected_index]
            ledger = score_double_ledger(selected.output, state)
            rows.append(
                {
                    "state_id": state.state_id,
                    "episode_id": state.episode_id,
                    "step_index": state.step_index,
                    "family": state.family,
                    "split": state.split,
                    "selected_code": selected.code,
                    "selected_route": selected.route,
                    "oracle_route": space.oracle_route,
                    "available_routes": list(space.routes),
                    "action_log_probs": [round(float(value), 10) for value in log_probs.cpu()],
                    "selected_probability": round(float(log_probs[selected_index].exp().item()), 10),
                    "action_entropy": round(float(action_entropy(log_probs).item()), 10),
                    "true_token_entropy": round(float(true_token_entropy(full_logits).item()), 10),
                    "prompt_tokens": int(encoded["attention_mask"].sum().item()),
                    "raw_policy_output": selected.output,
                    "double_ledger": ledger.to_dict(),
                }
            )
            if index % 50 == 0 or index == len(states):
                print(canonical_json({"evaluated": index, "total": len(states), "split": split}), flush=True)
    predictions_path = output_dir / "predictions.jsonl"
    with predictions_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")
    summary = summarize_predictions(rows, states=states)
    summary.update(
        {
            "schema_version": "studyhub.agent.router_rl.evaluation.v2",
            "split": split,
            "seed": seed,
            "model_path": str(model_path.resolve()),
            "adapter_path": str(adapter_path.resolve()) if adapter_path else None,
            "adapter_sha256": (
                sha256_file(adapter_path / "adapter_model.safetensors")
                if adapter_path
                else "frozen_sft_v1_7_merged"
            ),
            "dataset_path": str(dataset_path.resolve()),
            "dataset_sha256": sha256_file(dataset_path),
            "decoding": {
                "type": "constrained_single_token_argmax",
                "batch_size": 1,
                "action_temperature": action_temperature,
                "max_prompt_tokens": max_prompt_tokens,
                "decode_limit_rate": 0.0,
            },
            "predictions_path": str(predictions_path.resolve()),
            "predictions_sha256": sha256_file(predictions_path),
            "gpu": {
                "name": torch.cuda.get_device_name(),
                "peak_memory_mib": round(torch.cuda.max_memory_allocated() / (1024**2), 3),
            },
            "isolation": {
                "production_api_called": False,
                "production_database_accessed": False,
                "production_oss_write_called": False,
                "paid_material_used": False,
                "legacy_v1_test_used": False,
                "production_final_holdout_read": False,
            },
        }
    )
    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "studyhub.agent.router_rl.evaluation_manifest.v2",
        "summary_path": str(summary_path.resolve()),
        "summary_sha256": sha256_file(summary_path),
        "predictions_sha256": sha256_file(predictions_path),
        "split": split,
        "single_pass": split in {"test", "sealed"},
        "production_access": False,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    del policy
    torch.cuda.empty_cache()
    return summary


def summarize_predictions(
    rows: list[dict[str, Any]],
    *,
    states: list[MaturityRouterState],
) -> dict[str, Any]:
    if len(rows) != len(states):
        raise ValueError("evaluation must produce exactly one prediction per state")
    by_state = {row["state_id"]: row for row in rows}
    if len(by_state) != len(rows) or set(by_state) != {state.state_id for state in states}:
        raise ValueError("evaluation state coverage is incomplete or duplicated")
    raw = _ledger_metrics(rows, states=states, ledger_name="raw")
    executable = _ledger_metrics(rows, states=states, ledger_name="executable")
    corrections: Counter[str] = Counter()
    severity_values: list[int] = []
    dependency: list[float] = []
    for row in rows:
        ledger = row["double_ledger"]
        row_corrections = list(ledger.get("constraint_corrections") or [])
        corrections.update(row_corrections)
        severity_values.append(sum(CORRECTION_SEVERITY.get(value, 1) for value in row_corrections))
        dependency.append(float(ledger["constraint_dependency_delta"]))
    action_entropies = [float(row["action_entropy"]) for row in rows]
    token_entropies = [float(row["true_token_entropy"]) for row in rows]
    prompt_tokens = [int(row["prompt_tokens"]) for row in rows]
    raw_choice = float(raw["choice_success_rate"])
    executable_choice = float(executable["choice_success_rate"])
    return {
        "states": len(rows),
        "episodes": len({state.episode_id for state in states}),
        "raw": raw,
        "executable": executable,
        "raw_executable": {
            "reward_delta_mean": round(sum(dependency) / len(dependency), 6),
            "reward_delta_absolute_mean": round(
                sum(abs(value) for value in dependency) / len(dependency),
                6,
            ),
            "choice_success_gap": round(executable_choice - raw_choice, 6),
            "choice_success_gap_absolute": round(abs(executable_choice - raw_choice), 6),
        },
        "constraint": {
            "corrections": dict(sorted(corrections.items())),
            "correction_rate": round(sum(bool(value) for value in severity_values) / len(rows), 6),
            "severity_mean": round(sum(severity_values) / len(severity_values), 6),
            "severity_max": max(severity_values),
        },
        "entropy": {
            "action_mean": round(statistics.fmean(action_entropies), 8),
            "true_token_mean": round(statistics.fmean(token_entropies), 8),
        },
        "prompt_tokens": {
            "minimum": min(prompt_tokens),
            "maximum": max(prompt_tokens),
            "mean": round(statistics.fmean(prompt_tokens), 3),
        },
    }


def _ledger_metrics(
    rows: list[dict[str, Any]],
    *,
    states: list[MaturityRouterState],
    ledger_name: str,
) -> dict[str, Any]:
    state_by_id = {state.state_id: state for state in states}
    rewards: list[float] = []
    choices: dict[str, bool] = {}
    hard_gates: dict[str, list[bool]] = defaultdict(list)
    hacking: Counter[str] = Counter()
    family_rows: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    for row in rows:
        score = row["double_ledger"][ledger_name]
        reward = float(score["policy_reward"])
        components = score["components"]
        choice = components["tool_choice"] == 1.0 and components["stop_decision"] == 1.0
        rewards.append(reward)
        choices[row["state_id"]] = choice
        family_rows[row["family"]].append((reward, choice))
        hacking.update(score.get("reward_hacking_flags") or [])
        for name, passed in score["hard_gates"].items():
            hard_gates[name].append(bool(passed))
    episodes: dict[str, list[bool]] = defaultdict(list)
    for state_id, choice in choices.items():
        episodes[state_by_id[state_id].episode_id].append(choice)
    episode_success = [all(values) for values in episodes.values()]
    hacking_states = sum(
        bool(row["double_ledger"][ledger_name].get("reward_hacking_flags"))
        for row in rows
    )
    return {
        "policy_reward_mean": round(statistics.fmean(rewards), 6),
        "choice_success_rate": round(sum(choices.values()) / len(choices), 6),
        "episode_success_rate": round(sum(episode_success) / len(episode_success), 6),
        "hard_gates": {
            name: round(sum(values) / len(values), 6)
            for name, values in sorted(hard_gates.items())
        },
        "reward_hacking_flags": dict(sorted(hacking.items())),
        "reward_hacking_rate": round(hacking_states / len(rows), 6),
        "families": {
            family: {
                "samples": len(values),
                "reward_mean": round(statistics.fmean(value[0] for value in values), 6),
                "choice_success_rate": round(sum(value[1] for value in values) / len(values), 6),
            }
            for family, values in sorted(family_rows.items())
        },
    }


def _assert_offline_environment() -> None:
    active = [name for name in FORBIDDEN_ENDPOINT_VARS if os.getenv(name)]
    if active:
        raise RuntimeError(f"offline evaluation refuses configured endpoints: {active}")
    if os.getenv("HF_HUB_OFFLINE") != "1" or os.getenv("TRANSFORMERS_OFFLINE") != "1":
        raise RuntimeError("offline evaluation requires local-only Hugging Face mode")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--split", choices=("validation", "test", "sealed"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--max-prompt-tokens", type=int, default=4096)
    parser.add_argument("--action-temperature", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=20260812)
    parser.add_argument("--allow-test", action="store_true")
    parser.add_argument("--allow-sealed", action="store_true")
    args = parser.parse_args()
    summary = evaluate_policy(
        model_path=args.model.resolve(),
        adapter_path=args.adapter.resolve() if args.adapter else None,
        dataset_path=args.dataset.resolve(),
        split=args.split,
        output_dir=args.output_dir.resolve(),
        device=args.device,
        max_prompt_tokens=args.max_prompt_tokens,
        action_temperature=args.action_temperature,
        seed=args.seed,
        allow_test=args.allow_test,
        allow_sealed=args.allow_sealed,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
