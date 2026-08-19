from __future__ import annotations

import gc
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.agentic_platform.deepresearch.prompts import (
    ResearchPromptPurpose,
    build_research_policy_view,
    render_research_prompt,
)
from app.agentic_platform.deepresearch.state import DeepResearchState, ResearchDecision


FORBIDDEN_ENDPOINT_VARS = (
    "DATABASE_URL",
    "MYSQL_URL",
    "STUDYHUB_DATABASE_URL",
    "OPENAI_BASE_URL",
    "ANTHROPIC_BASE_URL",
    "STUDYHUB_AGENTIC_MODEL_BASE_URL",
    "STUDYHUB_WEB_ROUTER_EVAL_MODEL_BASE_URL",
)


@dataclass(frozen=True, slots=True)
class LocalWebRouterPrediction:
    decision: ResearchDecision | None
    raw_generated: str
    error_type: str | None
    completion_tokens: int
    hit_decode_limit: bool


def generate_local_predictions(
    states: list[DeepResearchState],
    *,
    model_path: Path,
    adapter_path: Path | None,
    batch_size: int,
    max_new_tokens: int,
    device: str,
) -> tuple[list[LocalWebRouterPrediction], dict[str, object]]:
    """Run an isolated local model against the production ResearchDecision prompt."""

    _assert_offline()
    if not states:
        raise ValueError("local Web Router evaluation requires states")
    if batch_size <= 0 or max_new_tokens <= 0:
        raise ValueError("batch_size and max_new_tokens must be positive")
    if not model_path.is_dir():
        raise FileNotFoundError(f"local model directory does not exist: {model_path}")
    if adapter_path is not None and not adapter_path.is_dir():
        raise FileNotFoundError(
            f"local adapter directory does not exist: {adapter_path}"
        )

    import torch
    from transformers import AutoModelForMultimodalLM, AutoProcessor
    from transformers.utils import logging as transformers_logging

    transformers_logging.set_verbosity_error()
    transformers_logging.disable_progress_bar()
    processor = AutoProcessor.from_pretrained(
        model_path,
        trust_remote_code=True,
        local_files_only=True,
    )
    processor.tokenizer.padding_side = "left"
    model = AutoModelForMultimodalLM.from_pretrained(
        model_path,
        dtype=torch.bfloat16,
        trust_remote_code=True,
        local_files_only=True,
        low_cpu_mem_usage=True,
    )
    if adapter_path is not None:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, adapter_path, is_trainable=False)
    model = model.to(device)
    model.eval()
    if str(device).startswith("cuda"):
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(device)

    predictions: list[LocalWebRouterPrediction] = []
    generated_tokens = 0
    started = time.perf_counter()
    for start in range(0, len(states), batch_size):
        batch = states[start : start + batch_size]
        prompts = [_render_chat_prompt(processor, state) for state in batch]
        inputs = processor(text=prompts, padding=True, return_tensors="pt")
        inputs = {
            key: value.to(device) if hasattr(value, "to") else value
            for key, value in inputs.items()
        }
        prompt_length = int(inputs["input_ids"].shape[-1])
        with torch.inference_mode():
            output_ids = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                use_cache=True,
                pad_token_id=processor.tokenizer.pad_token_id,
                eos_token_id=processor.tokenizer.eos_token_id,
            )
        for output_row in output_ids:
            completion = output_row[prompt_length:]
            if processor.tokenizer.pad_token_id is not None:
                completion = completion[completion.ne(processor.tokenizer.pad_token_id)]
            token_count = int(completion.numel())
            generated_tokens += token_count
            raw = processor.tokenizer.decode(
                completion.detach().cpu(),
                skip_special_tokens=True,
            ).strip()
            decision, error_type = parse_research_decision(raw)
            predictions.append(
                LocalWebRouterPrediction(
                    decision=decision,
                    raw_generated=raw,
                    error_type=error_type,
                    completion_tokens=token_count,
                    hit_decode_limit=token_count >= max_new_tokens,
                )
            )
        print(
            json.dumps(
                {"completed": len(predictions), "total": len(states)},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            flush=True,
        )

    elapsed = time.perf_counter() - started
    runtime: dict[str, object] = {
        "elapsed_seconds": round(elapsed, 3),
        "generated_tokens": generated_tokens,
        "generated_tokens_per_second": round(generated_tokens / elapsed, 3),
        "batch_size": batch_size,
        "max_new_tokens": max_new_tokens,
        "device": device,
    }
    if str(device).startswith("cuda"):
        runtime["peak_cuda_memory_mib"] = round(
            torch.cuda.max_memory_allocated(device) / (1024**2),
            3,
        )
    del model
    gc.collect()
    if str(device).startswith("cuda"):
        torch.cuda.empty_cache()
    return predictions, runtime


def _render_chat_prompt(processor: Any, state: DeepResearchState) -> str:
    messages = build_research_decision_messages(state)
    return processor.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )


def build_research_decision_messages(
    state: DeepResearchState,
) -> list[dict[str, str]]:
    view = build_research_policy_view(
        state,
        purpose=ResearchPromptPurpose.POLICY,
        token_budget=min(12_000, state.budget.remaining_context_tokens),
    )
    prompt = render_research_prompt(view, ResearchDecision)
    return [
        {
            "role": "system",
            "content": (
                "Return exactly one JSON object. Do not reveal hidden reasoning. "
                'JSON example: {"result":"schema-compliant value"}.'
            ),
        },
        {"role": "user", "content": prompt.rendered_prompt},
    ]


def parse_research_decision(
    raw: str,
) -> tuple[ResearchDecision | None, str | None]:
    raw = extract_first_json_object(raw)
    if not raw.startswith("{") or not raw.endswith("}") or "<think>" in raw:
        return None, "invalid_json_envelope"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None, "invalid_json"
    if not isinstance(payload, dict):
        return None, "json_not_object"
    try:
        return ResearchDecision.model_validate(payload), None
    except ValidationError:
        return None, "research_decision_validation"


def extract_first_json_object(raw: str) -> str:
    """Bound a free-generation response to its first complete top-level JSON object."""

    stripped = raw.strip()
    if not stripped.startswith("{"):
        return stripped
    try:
        payload, end = json.JSONDecoder().raw_decode(stripped)
    except json.JSONDecodeError:
        return stripped
    if not isinstance(payload, dict):
        return stripped
    return stripped[:end]


def _assert_offline() -> None:
    active = [name for name in FORBIDDEN_ENDPOINT_VARS if os.getenv(name)]
    if active:
        raise RuntimeError(
            f"local Web Router evaluation refuses configured endpoints: {active}"
        )
    if os.getenv("HF_HUB_OFFLINE") != "1" or os.getenv("TRANSFORMERS_OFFLINE") != "1":
        raise RuntimeError("local Web Router evaluation requires local-only model mode")


__all__ = [
    "LocalWebRouterPrediction",
    "build_research_decision_messages",
    "extract_first_json_object",
    "generate_local_predictions",
    "parse_research_decision",
]
