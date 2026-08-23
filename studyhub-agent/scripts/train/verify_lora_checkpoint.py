#!/usr/bin/env python3
"""Reload an AReaL LoRA checkpoint and run a bounded text-generation smoke test."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--model", type=Path, default=project.parent / "models/P0/Qwen3.5-2B")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--memory-fraction", type=float, default=0.25)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    import torch
    from peft import PeftModel
    from transformers import AutoModelForImageTextToText, AutoTokenizer

    if not 0 < args.memory_fraction <= 0.25:
        raise ValueError("memory-fraction must be in (0, 0.25]")
    torch.cuda.set_per_process_memory_fraction(args.memory_fraction, device=0)
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    base = AutoModelForImageTextToText.from_pretrained(
        args.model,
        trust_remote_code=True,
        dtype=torch.bfloat16,
        attn_implementation="sdpa",
        device_map={"": 0},
    )
    model = PeftModel.from_pretrained(base, args.checkpoint, is_trainable=False)
    model.eval()
    messages = [{"role": "user", "content": "只回复：检查通过"}]
    encoded = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        enable_thinking=False,
        return_tensors="pt",
    )
    prompt = encoded["input_ids"] if hasattr(encoded, "keys") else encoded
    prompt = prompt.to("cuda")
    with torch.inference_mode():
        generated = model.generate(
            input_ids=prompt,
            attention_mask=torch.ones_like(prompt),
            pad_token_id=tokenizer.eos_token_id,
            max_new_tokens=16,
            do_sample=False,
            use_cache=True,
        )
    response = tokenizer.decode(generated[0, prompt.shape[-1] :], skip_special_tokens=True).strip()
    adapter = args.checkpoint / "adapter_model.safetensors"
    result = {
        "schema_version": "studyhub.lora-reload-check.v1",
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "checkpoint": str(args.checkpoint.resolve()),
        "adapter_sha256": sha256(adapter),
        "adapter_bytes": adapter.stat().st_size,
        "memory_fraction_limit": args.memory_fraction,
        "peak_memory_allocated_mib": round(torch.cuda.max_memory_allocated() / 1024**2, 2),
        "generation": response,
        "status": "passed" if response else "failed",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if response else 1


if __name__ == "__main__":
    raise SystemExit(main())
