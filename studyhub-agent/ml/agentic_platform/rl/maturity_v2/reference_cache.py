"""Precompute immutable SFT reference distributions for offline Router RL."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from ..spec import canonical_json, sha256_file
from .actions import build_action_space
from .policy import (
    action_entropy,
    available_action_log_probs,
    decision_prompt,
    encode_prompts,
    final_token_logits,
    load_base_policy,
    load_processor,
    true_token_entropy,
)
from .spec import load_maturity_states

FORBIDDEN_ENDPOINT_VARS = (
    "DATABASE_URL",
    "MYSQL_URL",
    "STUDYHUB_DATABASE_URL",
    "OPENAI_BASE_URL",
    "ANTHROPIC_BASE_URL",
    "STUDYHUB_AGENTIC_MODEL_BASE_URL",
)


def build_reference_cache(
    *,
    model_path: Path,
    train_path: Path,
    output_dir: Path,
    device: str,
    batch_size: int,
    max_prompt_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    _assert_offline_environment()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite reference cache: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    states = load_maturity_states(train_path, splits={"train"})

    import torch
    from transformers.utils import logging as transformers_logging

    transformers_logging.set_verbosity_error()
    transformers_logging.disable_progress_bar()
    processor = load_processor(model_path)
    model = load_base_policy(model_path, device=device, trainable=False)
    model.eval()
    rows: list[dict[str, Any]] = []
    family_counts: Counter[str] = Counter()
    prompt_tokens: list[int] = []
    with torch.no_grad():
        for start in range(0, len(states), batch_size):
            batch = states[start : start + batch_size]
            spaces = [build_action_space(state) for state in batch]
            prompts = [
                decision_prompt(processor, state, space)
                for state, space in zip(batch, spaces, strict=True)
            ]
            encoded = encode_prompts(
                processor,
                prompts,
                device=device,
                max_prompt_tokens=max_prompt_tokens,
            )
            logits = final_token_logits(model, encoded)
            lengths = encoded["attention_mask"].sum(dim=1).detach().cpu().tolist()
            for index, (state, space) in enumerate(zip(batch, spaces, strict=True)):
                log_probs = available_action_log_probs(
                    logits[index],
                    space=space,
                    tokenizer=processor.tokenizer,
                    temperature=temperature,
                )
                rows.append(
                    {
                        "state_id": state.state_id,
                        "family": state.family,
                        "routes": list(space.routes),
                        "codes": list(space.codes),
                        "log_probs": [round(float(value), 10) for value in log_probs.detach().cpu()],
                        "action_entropy": round(float(action_entropy(log_probs).item()), 10),
                        "true_token_entropy": round(
                            float(true_token_entropy(logits[index]).item()),
                            10,
                        ),
                        "prompt_tokens": int(lengths[index]),
                    }
                )
                family_counts[state.family] += 1
                prompt_tokens.append(int(lengths[index]))
            print(
                canonical_json(
                    {
                        "cached": min(start + len(batch), len(states)),
                        "total": len(states),
                    }
                ),
                flush=True,
            )
    cache_path = output_dir / "train_reference.jsonl"
    with cache_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")
    summary = {
        "schema_version": "studyhub.agent.router_rl.reference_cache.v2",
        "model_path": str(model_path.resolve()),
        "train_path": str(train_path.resolve()),
        "train_sha256": sha256_file(train_path),
        "states": len(rows),
        "family_counts": dict(sorted(family_counts.items())),
        "temperature": temperature,
        "batch_size": batch_size,
        "max_prompt_tokens": max_prompt_tokens,
        "prompt_tokens": {
            "minimum": min(prompt_tokens),
            "maximum": max(prompt_tokens),
            "mean": round(sum(prompt_tokens) / len(prompt_tokens), 3),
        },
        "cache_path": str(cache_path.resolve()),
        "cache_sha256": sha256_file(cache_path),
        "test_read": False,
        "sealed_read": False,
        "production_access": False,
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def load_reference_cache(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            value = json.loads(line)
            state_id = str(value.get("state_id") or "")
            if not state_id or state_id in result:
                raise ValueError(f"invalid or duplicate reference state at line {line_number}")
            routes = value.get("routes")
            log_probs = value.get("log_probs")
            if not isinstance(routes, list) or not isinstance(log_probs, list) or len(routes) != len(log_probs):
                raise ValueError(f"malformed reference distribution at line {line_number}")
            result[state_id] = value
    return result


def _assert_offline_environment() -> None:
    active = [name for name in FORBIDDEN_ENDPOINT_VARS if os.getenv(name)]
    if active:
        raise RuntimeError(f"reference cache refuses configured endpoints: {active}")
    if os.getenv("HF_HUB_OFFLINE") != "1" or os.getenv("TRANSFORMERS_OFFLINE") != "1":
        raise RuntimeError("reference cache requires local-only Hugging Face mode")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--max-prompt-tokens", type=int, default=4096)
    parser.add_argument("--temperature", type=float, default=1.0)
    args = parser.parse_args()
    summary = build_reference_cache(
        model_path=args.model.resolve(),
        train_path=args.train.resolve(),
        output_dir=args.output_dir.resolve(),
        device=args.device,
        batch_size=args.batch_size,
        max_prompt_tokens=args.max_prompt_tokens,
        temperature=args.temperature,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
