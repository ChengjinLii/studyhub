"""Evaluate SFT and RL Router policies on independent offline states."""

from __future__ import annotations

import argparse
import gc
import json
import os
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .reward import score_double_ledger
from .spec import RouterRLState, canonical_json, load_states, sha256_file

FORBIDDEN_ENDPOINT_VARS = (
    "DATABASE_URL",
    "MYSQL_URL",
    "STUDYHUB_DATABASE_URL",
    "OPENAI_BASE_URL",
    "ANTHROPIC_BASE_URL",
    "STUDYHUB_AGENTIC_MODEL_BASE_URL",
)


def evaluate(
    *,
    model_path: Path,
    adapter_path: Path,
    dataset_path: Path,
    split: str,
    output_dir: Path,
    batch_size: int = 6,
    max_new_tokens: int = 320,
    do_sample: bool = False,
    temperature: float = 0.7,
    top_p: float = 0.95,
    samples_per_state: int = 1,
    seed: int = 20260812,
) -> dict[str, Any]:
    _assert_offline()
    if split not in {"validation", "test"}:
        raise ValueError("RL evaluation only accepts validation or test")
    if samples_per_state < 1 or (not do_sample and samples_per_state != 1):
        raise ValueError("greedy evaluation requires one sample per state")
    states = load_states(dataset_path, splits={split})
    if not states:
        raise ValueError("RL evaluation selection is empty")
    output_dir.mkdir(parents=True, exist_ok=True)

    import torch
    from peft import PeftModel
    from transformers import AutoModelForMultimodalLM, AutoProcessor
    from transformers.utils import logging as transformers_logging

    transformers_logging.set_verbosity_error()
    transformers_logging.disable_progress_bar()
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True, local_files_only=True)
    processor.tokenizer.padding_side = "left"
    model = AutoModelForMultimodalLM.from_pretrained(
        model_path,
        dtype=torch.bfloat16,
        trust_remote_code=True,
        local_files_only=True,
        low_cpu_mem_usage=True,
    ).to("cuda")
    model = PeftModel.from_pretrained(model, adapter_path, is_trainable=False)
    model.eval()
    expanded = [(state, sample_index) for state in states for sample_index in range(samples_per_state)]
    rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    generated_tokens = 0
    for start in range(0, len(expanded), batch_size):
        batch = expanded[start : start + batch_size]
        prompts = [
            processor.apply_chat_template(
                list(state.messages),
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            for state, _sample_index in batch
        ]
        inputs = processor(text=prompts, padding=True, return_tensors="pt")
        inputs = {key: value.to("cuda") if hasattr(value, "to") else value for key, value in inputs.items()}
        prompt_length = int(inputs["input_ids"].shape[1])
        generation_kwargs: dict[str, Any] = {
            "max_new_tokens": max_new_tokens,
            "do_sample": do_sample,
            "use_cache": True,
            "pad_token_id": processor.tokenizer.pad_token_id,
            "eos_token_id": processor.tokenizer.eos_token_id,
        }
        if do_sample:
            generation_kwargs.update({"temperature": temperature, "top_p": top_p})
        with torch.inference_mode():
            output_ids = model.generate(**inputs, **generation_kwargs)
        for (state, sample_index), output_row in zip(batch, output_ids, strict=True):
            completion = output_row[prompt_length:]
            if processor.tokenizer.pad_token_id is not None:
                completion = completion[completion.ne(processor.tokenizer.pad_token_id)]
            token_count = int(completion.numel())
            generated_tokens += token_count
            text = processor.tokenizer.decode(completion.detach().cpu(), skip_special_tokens=True).strip()
            ledger = score_double_ledger(text, state)
            rows.append(
                {
                    "state_id": state.state_id,
                    "episode_id": state.episode_id,
                    "split": state.split,
                    "family": state.family,
                    "sample_index": sample_index,
                    "raw_generated": text,
                    "completion_tokens": token_count,
                    "hit_decode_limit": token_count >= max_new_tokens,
                    "double_ledger": ledger.to_dict(),
                }
            )
        print(canonical_json({"completed": len(rows), "total": len(expanded)}), flush=True)
    elapsed = time.perf_counter() - started
    predictions_path = output_dir / "predictions.jsonl"
    predictions_path.write_text("".join(canonical_json(row) + "\n" for row in rows), encoding="utf-8")
    summary = summarize_rows(rows, states=states)
    summary.update(
        {
            "schema_version": "studyhub.agent.router_rl.evaluation.v1",
            "model_path": str(model_path.resolve()),
            "adapter_path": str(adapter_path.resolve()),
            "adapter_sha256": sha256_file(adapter_path / "adapter_model.safetensors"),
            "dataset_path": str(dataset_path.resolve()),
            "dataset_sha256": sha256_file(dataset_path),
            "split": split,
            "decoding": {
                "do_sample": do_sample,
                "temperature": temperature if do_sample else None,
                "top_p": top_p if do_sample else None,
                "samples_per_state": samples_per_state,
                "max_new_tokens": max_new_tokens,
                "seed": seed,
            },
            "runtime": {
                "elapsed_seconds": round(elapsed, 3),
                "generated_tokens": generated_tokens,
                "generated_tokens_per_second": round(generated_tokens / elapsed, 3),
                "peak_cuda_memory_mib": round(torch.cuda.max_memory_allocated() / (1024**2), 3),
            },
            "predictions_path": str(predictions_path.resolve()),
            "predictions_sha256": sha256_file(predictions_path),
            "isolation": {
                "production_api_called": False,
                "production_database_accessed": False,
                "production_oss_write_called": False,
                "paid_material_used": False,
                "development_diagnostic_read": False,
                "final_holdout_read": False,
            },
        }
    )
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    del model
    gc.collect()
    torch.cuda.empty_cache()
    return summary


def summarize_rows(rows: list[dict[str, Any]], *, states: list[RouterRLState]) -> dict[str, Any]:
    if not rows:
        raise ValueError("cannot summarize empty RL predictions")
    by_state = {state.state_id: state for state in states}
    row_state_ids = {str(row["state_id"]) for row in rows}
    unknown_state_ids = sorted(row_state_ids - set(by_state))
    missing_state_ids = sorted(set(by_state) - row_state_ids)
    if unknown_state_ids:
        raise ValueError(f"predictions contain unknown states: {unknown_state_ids}")
    if missing_state_ids:
        raise ValueError(f"predictions omit states: {missing_state_ids}")
    sample_keys = [(str(row["state_id"]), int(row["sample_index"])) for row in rows]
    if len(sample_keys) != len(set(sample_keys)):
        raise ValueError("predictions contain duplicate state/sample pairs")
    for row in rows:
        state = by_state[str(row["state_id"])]
        if str(row["episode_id"]) != state.episode_id or str(row["family"]) != state.family:
            raise ValueError(f"prediction metadata mismatch for state {state.state_id}")
    ledgers = [row["double_ledger"] for row in rows]
    raw_rewards = [float(item["raw"]["policy_reward"]) for item in ledgers]
    executable_rewards = [float(item["executable"]["policy_reward"]) for item in ledgers]
    raw_choice = [_choice_success(item["raw"]) for item in ledgers]
    executable_choice = [_choice_success(item["executable"]) for item in ledgers]
    components: dict[str, list[float]] = defaultdict(list)
    hard_gates: dict[str, list[bool]] = defaultdict(list)
    executable_gates: dict[str, list[bool]] = defaultdict(list)
    family_rewards: dict[str, list[float]] = defaultdict(list)
    family_choice: dict[str, list[bool]] = defaultdict(list)
    hacking: Counter[str] = Counter()
    corrections: Counter[str] = Counter()
    source_status: Counter[str] = Counter()
    for row, ledger in zip(rows, ledgers, strict=True):
        family = str(row["family"])
        family_rewards[family].append(float(ledger["raw"]["policy_reward"]))
        family_choice[family].append(_choice_success(ledger["raw"]))
        for name, value in ledger["raw"]["components"].items():
            if value is not None:
                components[name].append(float(value))
        for name, value in ledger["raw"]["hard_gates"].items():
            hard_gates[name].append(bool(value))
        for name, value in ledger["executable"]["hard_gates"].items():
            executable_gates[name].append(bool(value))
        hacking.update(ledger["raw"]["reward_hacking_flags"])
        corrections.update(ledger["constraint_corrections"])
        source_status[str(ledger["constraint_source_status"])] += 1
    episode_samples: dict[tuple[str, int], list[bool]] = defaultdict(list)
    for row, passed in zip(rows, raw_choice, strict=True):
        episode_samples[(str(row["episode_id"]), int(row["sample_index"]))].append(passed)
    episode_success = [all(values) for values in episode_samples.values()]
    return {
        "states": len(states),
        "predictions": len(rows),
        "raw": {
            "policy_reward_mean": _mean(raw_rewards),
            "policy_reward_std": _population_std(raw_rewards),
            "choice_success_rate": _rate(raw_choice),
            "episode_success_rate": _rate(episode_success),
            "components": {name: _mean(values) for name, values in sorted(components.items())},
            "hard_gates": {name: _rate(values) for name, values in sorted(hard_gates.items())},
            "families": {
                family: {"reward_mean": _mean(values), "choice_success_rate": _rate(family_choice[family]), "samples": len(values)}
                for family, values in sorted(family_rewards.items())
            },
            "reward_hacking_flags": dict(sorted(hacking.items())),
        },
        "executable": {
            "policy_reward_mean": _mean(executable_rewards),
            "choice_success_rate": _rate(executable_choice),
            "hard_gates": {name: _rate(values) for name, values in sorted(executable_gates.items())},
        },
        "constraint_dependency_delta_mean": round(_mean(executable_rewards) - _mean(raw_rewards), 6),
        "constraint": {"source_status": dict(sorted(source_status.items())), "corrections": dict(sorted(corrections.items()))},
        "decode_limit_hits": sum(bool(row["hit_decode_limit"]) for row in rows),
        "completion_tokens_mean": _mean([float(row["completion_tokens"]) for row in rows]),
    }


def _choice_success(ledger: dict[str, Any]) -> bool:
    components = ledger["components"]
    return components.get("tool_choice") == 1.0 and components.get("stop_decision") == 1.0


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def _population_std(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return round((sum((value - mean) ** 2 for value in values) / len(values)) ** 0.5, 6)


def _rate(values: list[bool]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def _assert_offline() -> None:
    active = [name for name in FORBIDDEN_ENDPOINT_VARS if os.getenv(name)]
    if active:
        raise RuntimeError(f"offline RL evaluation refuses configured endpoints: {active}")
    if os.getenv("HF_HUB_OFFLINE") != "1" or os.getenv("TRANSFORMERS_OFFLINE") != "1":
        raise RuntimeError("offline model evaluation requires local-only mode")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--split", choices=("validation", "test"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=6)
    parser.add_argument("--max-new-tokens", type=int, default=320)
    parser.add_argument("--do-sample", action="store_true")
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--samples-per-state", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260812)
    args = parser.parse_args()
    summary = evaluate(
        model_path=args.model.resolve(),
        adapter_path=args.adapter.resolve(),
        dataset_path=args.dataset.resolve(),
        split=args.split,
        output_dir=args.output_dir.resolve(),
        batch_size=args.batch_size,
        max_new_tokens=args.max_new_tokens,
        do_sample=args.do_sample,
        temperature=args.temperature,
        top_p=args.top_p,
        samples_per_state=args.samples_per_state,
        seed=args.seed,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
