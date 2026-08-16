"""Evaluate strict StudyHub router JSON for a base model or LoRA adapter."""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from app.services.agent_router_constraint_service import constrain_router_output
from app.services.agent_tool_loop_service import (
    AGENT_TOOL_LOOP_CONTINUE_INSTRUCTION,
    AGENT_TOOL_LOOP_FORCE_FINAL_INSTRUCTION,
    AGENT_TOOL_LOOP_SYSTEM_PROMPT,
    build_agent_routing_state,
)

from .build_validation_dataset import DEFAULT_OUTPUT_DIR
from .router_state import normalize_router_payload
from .spec import (
    ALLOWED_TOOLS,
    DatasetSpecError,
    canonical_json,
    load_jsonl,
    validate_assistant_target,
)

DEFAULT_MODEL = Path("/data/chengjin/studyhub/models/P0/Qwen3.5-2B")
DEFAULT_DATASET = DEFAULT_OUTPUT_DIR / "router_tool_2b.jsonl"
DEFAULT_MAX_NEW_TOKENS = 384
PRODUCTION_MAX_NEW_TOKENS = 1800


def _resolve_max_new_tokens(
    requested: int | None,
    *,
    production_contract: bool,
) -> int:
    value = requested
    if value is None:
        value = (
            PRODUCTION_MAX_NEW_TOKENS if production_contract else DEFAULT_MAX_NEW_TOKENS
        )
    if isinstance(value, bool) or value <= 0:
        raise ValueError("max_new_tokens must be a positive integer")
    return value


def _install_set_submodule_compat(module_type: type[Any]) -> bool:
    """Backport the PyTorch module replacement API required by NF4 loading."""
    if hasattr(module_type, "set_submodule"):
        return False

    def set_submodule(
        self: Any,
        target: str,
        module: Any,
        strict: bool = False,
    ) -> None:
        if not target or target.startswith(".") or target.endswith("."):
            raise ValueError(f"invalid submodule target: {target!r}")
        atoms = target.split(".")
        if any(not atom for atom in atoms):
            raise ValueError(f"invalid submodule target: {target!r}")
        parent = self.get_submodule(".".join(atoms[:-1])) if len(atoms) > 1 else self
        name = atoms[-1]
        if strict and not hasattr(parent, name):
            raise AttributeError(f"submodule {target!r} does not exist")
        setattr(parent, name, module)

    module_type.set_submodule = set_submodule
    return True


def _strict_json(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if (
        stripped.startswith("```")
        or not stripped.startswith("{")
        or not stripped.endswith("}")
    ):
        return None
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or "<think>" in text or "</think>" in text:
        return None
    return value


def _score(
    expected: dict[str, Any], predicted: dict[str, Any] | None
) -> dict[str, bool]:
    result = {
        "json_valid": predicted is not None,
        "contract_valid": False,
        "mode_correct": False,
        "tool_name_correct": False,
        "arguments_exact": False,
        "policy_refusal": False,
    }
    if predicted is None:
        return result
    try:
        validate_assistant_target(predicted, profile="router_tool_2b")
    except DatasetSpecError:
        pass
    else:
        result["contract_valid"] = True
    expected_mode = expected.get("mode")
    predicted_mode = predicted.get("mode")
    result["mode_correct"] = predicted_mode == expected_mode
    if expected_mode == "tools":
        expected_actions = expected.get("actions")
        predicted_actions = predicted.get("actions")
        if not isinstance(expected_actions, list) or not expected_actions:
            return result
        if not isinstance(predicted_actions, list) or not predicted_actions:
            return result
        expected_action = expected_actions[0]
        predicted_action = predicted_actions[0]
        if not isinstance(expected_action, dict) or not isinstance(
            predicted_action, dict
        ):
            return result
        predicted_name = predicted_action.get("name")
        result["tool_name_correct"] = (
            predicted_name == expected_action.get("name")
            and predicted_name in ALLOWED_TOOLS
        )
        result["arguments_exact"] = result["tool_name_correct"] and canonical_json(
            predicted_action.get("arguments")
        ) == canonical_json(expected_action.get("arguments"))
    elif expected_mode == "final":
        result["tool_name_correct"] = predicted_mode == "final"
        result["arguments_exact"] = predicted_mode == "final"
        answer = str(predicted.get("answer") or "")
        result["policy_refusal"] = any(
            phrase in answer
            for phrase in ("不能", "无法", "不可以", "只读", "权限", "隐私", "付费")
        )
    return result


def _load_runtime(
    model_path: Path,
    adapter_path: Path | None,
    *,
    precision: str = "bf16",
):
    import torch
    from transformers import (
        AutoModelForMultimodalLM,
        AutoProcessor,
        BitsAndBytesConfig,
    )

    if precision not in {"bf16", "nf4"}:
        raise ValueError(f"unsupported inference precision: {precision}")

    processor = AutoProcessor.from_pretrained(
        model_path,
        trust_remote_code=True,
        local_files_only=True,
    )
    processor.tokenizer.padding_side = "left"
    model_kwargs: dict[str, Any] = {
        "dtype": torch.bfloat16,
        "trust_remote_code": True,
        "local_files_only": True,
        "low_cpu_mem_usage": True,
    }
    if precision == "nf4":
        _install_set_submodule_compat(torch.nn.Module)
        model_kwargs.update(
            {
                "device_map": {"": torch.cuda.current_device()},
                "quantization_config": BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=torch.bfloat16,
                    bnb_4bit_use_double_quant=True,
                ),
            }
        )
    model = AutoModelForMultimodalLM.from_pretrained(model_path, **model_kwargs)
    if adapter_path is not None:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, adapter_path, is_trainable=False)
    if precision == "bf16":
        model = model.to("cuda")
    model.eval()
    return processor, model


def _generate_batch(
    processor,
    model,
    message_batches: list[list[dict[str, str]]],
    *,
    max_new_tokens: int,
) -> list[str]:
    import torch

    prompts = [
        processor.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        for messages in message_batches
    ]
    inputs = processor(text=prompts, padding=True, return_tensors="pt")
    inputs = {
        key: value.to(model.device) if hasattr(value, "to") else value
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
    return [
        processor.tokenizer.decode(
            output_row[prompt_length:],
            skip_special_tokens=True,
        ).strip()
        for output_row in output_ids
    ]


def _evaluation_messages(
    record: dict[str, Any],
    *,
    normalize_routing_state: bool,
    production_contract: bool = False,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for item in record["messages"]:
        if item["role"] == "assistant":
            continue
        content = str(item["content"])
        if production_contract and item["role"] == "system":
            content = AGENT_TOOL_LOOP_SYSTEM_PROMPT
        if item["role"] == "user" and (production_contract or normalize_routing_state):
            payload = json.loads(content)
            if production_contract:
                payload["instruction"] = (
                    AGENT_TOOL_LOOP_FORCE_FINAL_INSTRUCTION
                    if payload.get("force_final")
                    else AGENT_TOOL_LOOP_CONTINUE_INSTRUCTION
                )
                if normalize_routing_state:
                    payload["routing_state"] = build_agent_routing_state(payload)
            else:
                payload = normalize_router_payload(payload)
            content = canonical_json(payload)
        messages.append({"role": item["role"], "content": content})
    return messages


def _request_payload(messages: list[dict[str, str]]) -> dict[str, Any]:
    for message in messages:
        if message.get("role") != "user":
            continue
        try:
            value = json.loads(str(message.get("content") or ""))
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def _decode_generated_output(
    generated: str,
    messages: list[dict[str, str]],
    *,
    constrained_decoding: bool,
    deterministic_argument_protection: bool,
) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
    if not constrained_decoding:
        return generated, _strict_json(generated), None
    constrained = constrain_router_output(
        generated,
        _request_payload(messages),
        protect_deterministic_arguments=deterministic_argument_protection,
    )
    emitted = canonical_json(constrained.value)
    return (
        emitted,
        constrained.value,
        {
            "source_status": constrained.source_status,
            "corrections": list(constrained.corrections),
            "deterministic_route": constrained.deterministic_route,
        },
    )


def evaluate(
    *,
    model_path: Path,
    dataset_path: Path,
    output_dir: Path,
    adapter_path: Path | None = None,
    splits: set[str] | None = None,
    limit: int | None = None,
    max_new_tokens: int | None = None,
    batch_size: int = 8,
    normalize_routing_state: bool = False,
    production_contract: bool = False,
    precision: str = "bf16",
    constrained_decoding: bool = False,
    deterministic_argument_protection: bool = False,
) -> dict[str, Any]:
    import torch

    if deterministic_argument_protection and not constrained_decoding:
        raise ValueError(
            "deterministic_argument_protection requires constrained_decoding"
        )

    max_new_tokens = _resolve_max_new_tokens(
        max_new_tokens,
        production_contract=production_contract,
    )
    splits = splits or {"validation", "test"}
    records = [row for row in load_jsonl(dataset_path) if row.get("split") in splits]
    if limit is not None:
        records = records[:limit]
    if not records:
        raise ValueError("evaluation selection is empty")

    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    load_started = time.perf_counter()
    processor, model = _load_runtime(
        model_path,
        adapter_path,
        precision=precision,
    )
    load_elapsed = time.perf_counter() - load_started
    loaded_memory_mib = torch.cuda.memory_allocated() / (1024**2)
    totals: Counter[str] = Counter()
    family_totals: dict[str, Counter[str]] = defaultdict(Counter)
    output_rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    completed = 0
    generated_tokens = 0
    constraint_corrections: Counter[str] = Counter()
    constraint_source_status: Counter[str] = Counter()
    for batch_start in range(0, len(records), batch_size):
        batch = records[batch_start : batch_start + batch_size]
        input_messages = [
            _evaluation_messages(
                record,
                normalize_routing_state=normalize_routing_state,
                production_contract=production_contract,
            )
            for record in batch
        ]
        generated_rows = _generate_batch(
            processor,
            model,
            input_messages,
            max_new_tokens=max_new_tokens,
        )
        for record, input_message, raw_generated in zip(
            batch,
            input_messages,
            generated_rows,
            strict=True,
        ):
            generated_tokens += len(
                processor.tokenizer.encode(raw_generated, add_special_tokens=False)
            )
            generated, parsed, constraint = _decode_generated_output(
                raw_generated,
                input_message,
                constrained_decoding=constrained_decoding,
                deterministic_argument_protection=deterministic_argument_protection,
            )
            if constraint is not None:
                constraint_source_status[str(constraint["source_status"])] += 1
                constraint_corrections.update(constraint["corrections"])
            expected = dict(record["assistant_target"])
            scores = _score(expected, parsed)
            family = str(record["task_family"])
            for metric, passed in scores.items():
                totals[metric] += int(passed)
                family_totals[family][metric] += int(passed)
            output_row = {
                "example_id": record["example_id"],
                "split": record["split"],
                "task_family": family,
                "expected": expected,
                "generated": generated,
                "parsed": parsed,
                "scores": scores,
            }
            if constraint is not None:
                output_row.update(
                    {
                        "raw_generated": raw_generated,
                        "raw_parsed": _strict_json(raw_generated),
                        "constraint": constraint,
                    }
                )
            output_rows.append(output_row)
            completed += 1
            print(
                json.dumps(
                    {
                        "completed": completed,
                        "total": len(records),
                        "example_id": record["example_id"],
                        "json_valid": scores["json_valid"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    elapsed = time.perf_counter() - started
    count = len(records)
    summary = {
        "model_path": str(model_path),
        "adapter_path": str(adapter_path) if adapter_path else None,
        "dataset_path": str(dataset_path),
        "splits": sorted(splits),
        "records": count,
        "max_new_tokens": max_new_tokens,
        "batch_size": batch_size,
        "normalize_routing_state": normalize_routing_state,
        "production_contract": production_contract,
        "constrained_decoding": constrained_decoding,
        "deterministic_argument_protection": deterministic_argument_protection,
        "constraint_diagnostics": {
            "source_status": dict(sorted(constraint_source_status.items())),
            "corrections": dict(sorted(constraint_corrections.items())),
        },
        "elapsed_seconds": round(elapsed, 3),
        "seconds_per_record": round(elapsed / count, 4),
        "runtime": {
            "precision": precision,
            "model_load_seconds": round(load_elapsed, 3),
            "loaded_cuda_memory_mib": round(loaded_memory_mib, 3),
            "peak_cuda_memory_mib": round(
                torch.cuda.max_memory_allocated() / (1024**2),
                3,
            ),
            "generated_tokens": generated_tokens,
            "generated_tokens_per_second": round(
                generated_tokens / elapsed,
                3,
            ),
        },
        "metrics": {
            metric: {
                "passed": totals[metric],
                "total": count,
                "rate": round(totals[metric] / count, 6),
            }
            for metric in (
                "json_valid",
                "contract_valid",
                "mode_correct",
                "tool_name_correct",
                "arguments_exact",
            )
        },
        "policy_refusal": {
            "passed": sum(
                int(row["scores"]["policy_refusal"])
                for row in output_rows
                if row["task_family"] == "refuse_permission_bypass"
            ),
            "total": sum(
                1
                for row in output_rows
                if row["task_family"] == "refuse_permission_bypass"
            ),
        },
        "family_metrics": {
            family: {
                metric: {
                    "passed": counts[metric],
                    "total": sum(
                        1 for row in output_rows if row["task_family"] == family
                    ),
                }
                for metric in (
                    "json_valid",
                    "contract_valid",
                    "mode_correct",
                    "tool_name_correct",
                    "arguments_exact",
                )
            }
            for family, counts in sorted(family_totals.items())
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    label = "adapter" if adapter_path else "base"
    predictions_path = output_dir / f"{label}_predictions.jsonl"
    with predictions_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in output_rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    (output_dir / f"{label}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "evaluation",
    )
    parser.add_argument("--splits", default="validation,test")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-new-tokens", type=int)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--normalize-routing-state", action="store_true")
    parser.add_argument("--production-contract", action="store_true")
    parser.add_argument("--constrained-decoding", action="store_true")
    parser.add_argument(
        "--deterministic-argument-protection",
        action="store_true",
    )
    parser.add_argument("--precision", choices=("bf16", "nf4"), default="bf16")
    args = parser.parse_args()
    summary = evaluate(
        model_path=args.model,
        adapter_path=args.adapter,
        dataset_path=args.dataset,
        output_dir=args.output_dir,
        splits={item.strip() for item in args.splits.split(",") if item.strip()},
        limit=args.limit,
        max_new_tokens=args.max_new_tokens,
        batch_size=args.batch_size,
        normalize_routing_state=args.normalize_routing_state,
        production_contract=args.production_contract,
        precision=args.precision,
        constrained_decoding=args.constrained_decoding,
        deterministic_argument_protection=args.deterministic_argument_protection,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
