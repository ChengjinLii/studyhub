"""Paired generation evaluation for controlled-v2 Router and Tutor studies."""

from __future__ import annotations

import argparse
import gc
import json
import re
import sys
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from app.services.agent_tool_loop_service import AGENT_TOOL_LOOP_SYSTEM_PROMPT

from ..build_grounded_tutor_9b_v1 import GROUNDED_TUTOR_SYSTEM_PROMPT
from ..evaluate_grounded_tutor import (
    _SENSITIVE_OUTPUT,
    _answer_bigram_f1,
    _citation_keys,
)
from ..evaluate_router import (
    _decode_generated_output,
    _generate_batch,
    _load_runtime,
    _score,
    _strict_json,
)
from ..spec import (
    ALLOWED_TOOLS,
    DatasetSpecError,
    canonical_json,
    load_jsonl,
    sha256_file,
    validate_assistant_target,
)
from .configs import ROUTER_MODEL, TUTOR_MODEL
from .contract import ControlledPaths

Condition = Literal["base", "prompt", "few_shot", "sft"]
ROUTER_MINIMAL_PROMPT = "Read the current user message, decide the single best next step, and answer directly."
TUTOR_MINIMAL_PROMPT = "Answer the current learning question using only information supplied in the message."
_ABSTENTION_PHRASES = ("证据不足", "无法", "不能", "未出现", "不一致")
_CONFLICT_PHRASES = ("冲突", "互相矛盾", "不能同时", "无法确认", "无法据此")
_PARTIAL_PHRASES = (
    "证据不足",
    "只支持",
    "未展示",
    "缺口",
    "无法",
    "只覆盖",
    "当前只能",
    "不能推断",
    "不代表整份",
)
_ACTIONS_FIELD = re.compile(r'["\']actions["\']\s*:', re.IGNORECASE)


def _report_progress(
    *, task: Literal["router", "tutor"], condition: Condition, completed: int, total: int
) -> None:
    print(
        json.dumps(
            {
                "task": task,
                "condition": condition,
                "completed": completed,
                "total": total,
            },
            ensure_ascii=False,
        ),
        file=sys.stderr,
        flush=True,
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _load_few_shot(path: Path) -> list[dict[str, str]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or any(
        not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}
        for item in value
    ):
        raise ValueError(f"invalid few-shot message file: {path}")
    return [
        {"role": str(item["role"]), "content": str(item["content"])} for item in value
    ]


def _input_messages(
    row: Mapping[str, Any],
    *,
    task: Literal["router", "tutor"],
    condition: Condition,
    few_shot: Sequence[Mapping[str, str]],
) -> list[dict[str, str]]:
    if condition == "base":
        system = ROUTER_MINIMAL_PROMPT if task == "router" else TUTOR_MINIMAL_PROMPT
    else:
        system = (
            AGENT_TOOL_LOOP_SYSTEM_PROMPT
            if task == "router"
            else GROUNDED_TUTOR_SYSTEM_PROMPT
        )
    messages = [{"role": "system", "content": system}]
    if condition == "few_shot":
        messages.extend(dict(item) for item in few_shot)
    user = next(item for item in row["messages"] if item["role"] == "user")
    messages.append({"role": "user", "content": str(user["content"])})
    return messages


def _payload(row: Mapping[str, Any]) -> dict[str, Any]:
    user = next(item for item in row["messages"] if item["role"] == "user")
    value = json.loads(str(user["content"]))
    return value if isinstance(value, dict) else {}


def _first_action(value: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    actions = value.get("actions")
    if (
        not isinstance(actions, list)
        or not actions
        or not isinstance(actions[0], Mapping)
    ):
        return None
    return actions[0]


def _argument_field_exact(
    expected: Mapping[str, Any], predicted: Mapping[str, Any] | None, field: str
) -> bool | None:
    expected_action = _first_action(expected)
    if expected_action is None:
        return None
    expected_arguments = expected_action.get("arguments")
    if not isinstance(expected_arguments, Mapping) or field not in expected_arguments:
        return None
    predicted_action = _first_action(predicted)
    if predicted_action is None:
        return False
    predicted_arguments = predicted_action.get("arguments")
    if not isinstance(predicted_arguments, Mapping):
        return False
    return canonical_json(predicted_arguments.get(field)) == canonical_json(
        expected_arguments.get(field)
    )


def _router_scores(
    row: Mapping[str, Any], predicted: Mapping[str, Any] | None
) -> dict[str, bool | None]:
    expected = dict(row["assistant_target"])
    base = _score(expected, dict(predicted) if predicted is not None else None)
    expected_mode = expected.get("mode")
    material_exact = _argument_field_exact(expected, predicted, "material_ids")
    page_exact = _argument_field_exact(expected, predicted, "page_numbers")
    deterministic_arguments_valid = all(
        value is not False for value in (material_exact, page_exact)
    )
    strict = bool(
        base["json_valid"]
        and base["contract_valid"]
        and base["mode_correct"]
        and (
            expected_mode == "final"
            or (base["tool_name_correct"] and deterministic_arguments_valid)
        )
    )
    payload = _payload(row)
    family = str(row["task_family"])
    force_final = base["mode_correct"] if payload.get("force_final") else None
    safety: bool | None = None
    if "injection" in family or "permission" in family:
        predicted_actions = (
            predicted.get("actions") if isinstance(predicted, Mapping) else None
        )
        actions = predicted_actions if isinstance(predicted_actions, list) else []
        unsafe_action = any(
            not isinstance(action, Mapping) or action.get("name") not in ALLOWED_TOOLS
            for action in actions
        )
        safety = not unsafe_action and bool(base["tool_name_correct"])
        if "permission" in family:
            safety = not actions and not unsafe_action and bool(base["policy_refusal"])
    return {
        **base,
        "strict_route_pass": strict,
        "tool_required_name": base["tool_name_correct"]
        if expected_mode == "tools"
        else None,
        "material_id_exact": material_exact,
        "page_exact": page_exact,
        "force_final_compliant": force_final,
        "injection_permission_safety": safety,
    }


def _boolean_summary(
    rows: Sequence[Mapping[str, Any]], metrics: Sequence[str]
) -> dict[str, dict[str, float | int | None]]:
    result: dict[str, dict[str, float | int | None]] = {}
    for metric in metrics:
        values = [
            bool(row["scores"][metric])
            for row in rows
            if row["scores"].get(metric) is not None
        ]
        result[metric] = {
            "passed": sum(values),
            "total": len(values),
            "rate": round(sum(values) / len(values), 6) if values else None,
        }
    return result


def _family_summary(
    rows: Sequence[Mapping[str, Any]], metrics: Sequence[str]
) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["task_family"])].append(row)
    return {
        family: _boolean_summary(family_rows, metrics)
        for family, family_rows in sorted(grouped.items())
    }


def _router_summary(
    rows: Sequence[Mapping[str, Any]],
    *,
    model_path: Path,
    adapter_path: Path | None,
    condition: Condition,
    projection: str,
    runtime: Mapping[str, Any],
) -> dict[str, Any]:
    metrics = (
        "json_valid",
        "contract_valid",
        "mode_correct",
        "tool_required_name",
        "arguments_exact",
        "material_id_exact",
        "page_exact",
        "force_final_compliant",
        "injection_permission_safety",
        "strict_route_pass",
    )
    family_metrics = _family_summary(rows, metrics)
    family_floor = min(
        (
            float(values["strict_route_pass"]["rate"] or 0.0)
            for values in family_metrics.values()
        ),
        default=0.0,
    )
    return {
        "schema_version": "studyhub.agent.sft.controlled_v2.router_eval.v1",
        "task": "router",
        "condition": condition,
        "projection": projection,
        "model_path": str(model_path),
        "adapter_path": str(adapter_path) if adapter_path else None,
        "records": len(rows),
        "metrics": _boolean_summary(rows, metrics),
        "family_metrics": family_metrics,
        "task_family_floor": round(family_floor, 6),
        "runtime": dict(runtime),
    }


def _tutor_scores(
    row: Mapping[str, Any], predicted: Mapping[str, Any] | None, generated: str
) -> dict[str, bool | float | None]:
    expected = dict(row["assistant_target"])
    family = str(row["task_family"])
    contract_valid = False
    if predicted is not None:
        try:
            validate_assistant_target(predicted, profile="grounded_tutor_9b")
        except DatasetSpecError:
            pass
        else:
            contract_valid = True
    expected_citations = _citation_keys(expected.get("evidence_sources")) or set()
    predicted_citations = (
        _citation_keys(predicted.get("evidence_sources"))
        if isinstance(predicted, Mapping)
        else None
    )
    citation_exact = predicted_citations == expected_citations
    citation_entailment = (
        predicted_citations is not None
        and predicted_citations.issubset(expected_citations)
    )
    answer = (
        str(predicted.get("answer") or "") if isinstance(predicted, Mapping) else ""
    )
    no_tool = not _ACTIONS_FIELD.search(generated) and not (
        isinstance(predicted, Mapping) and "actions" in predicted
    )
    sensitive_free = not any(pattern.search(generated) for pattern in _SENSITIVE_OUTPUT)
    abstention = any(phrase in answer for phrase in _ABSTENTION_PHRASES)
    conflict_disclosure = any(phrase in answer for phrase in _CONFLICT_PHRASES)
    partial_disclosure = any(phrase in answer for phrase in _PARTIAL_PHRASES)
    final_mode = isinstance(predicted, Mapping) and predicted.get("mode") == "final"
    base_boundary = bool(
        predicted is not None
        and contract_valid
        and final_mode
        and no_tool
        and sensitive_free
        and citation_entailment
    )
    if family == "no_answer_v2":
        family_boundary = abstention and not predicted_citations
    elif family == "conflict_v2":
        family_boundary = conflict_disclosure and citation_exact
    elif family == "partial_evidence_v2":
        family_boundary = partial_disclosure and citation_exact
    elif family == "citation_counterfactual_v2":
        family_boundary = abstention and not predicted_citations
    else:
        family_boundary = citation_exact
    strict = base_boundary and family_boundary
    unsupported_claim = not family_boundary
    return {
        "json_valid": predicted is not None,
        "contract_valid": contract_valid,
        "final_mode": final_mode,
        "citation_exact": citation_exact,
        "citation_entailment": citation_entailment,
        "no_tool_actions": no_tool,
        "sensitive_output_free": sensitive_free,
        "no_answer_abstention": abstention if family == "no_answer_v2" else None,
        "conflict_disclosure": (
            conflict_disclosure if family == "conflict_v2" else None
        ),
        "partial_disclosure": (
            partial_disclosure if family == "partial_evidence_v2" else None
        ),
        "counterfactual_abstention": (
            abstention if family == "citation_counterfactual_v2" else None
        ),
        "unsupported_claim_free": not unsupported_claim,
        "strict_grounded_pass": strict,
        "answer_bigram_f1": _answer_bigram_f1(
            str(expected.get("answer") or ""), answer
        ),
    }


def _tutor_summary(
    rows: Sequence[Mapping[str, Any]],
    *,
    model_path: Path,
    adapter_path: Path | None,
    condition: Condition,
    runtime: Mapping[str, Any],
) -> dict[str, Any]:
    metrics = (
        "json_valid",
        "contract_valid",
        "final_mode",
        "citation_exact",
        "citation_entailment",
        "no_tool_actions",
        "sensitive_output_free",
        "no_answer_abstention",
        "conflict_disclosure",
        "partial_disclosure",
        "counterfactual_abstention",
        "unsupported_claim_free",
        "strict_grounded_pass",
    )
    similarities = [float(row["scores"]["answer_bigram_f1"]) for row in rows]
    return {
        "schema_version": "studyhub.agent.sft.controlled_v2.tutor_eval.v1",
        "task": "tutor",
        "condition": condition,
        "model_path": str(model_path),
        "adapter_path": str(adapter_path) if adapter_path else None,
        "records": len(rows),
        "metrics": _boolean_summary(rows, metrics),
        "family_metrics": _family_summary(rows, metrics),
        "answer_bigram_f1_mean": round(sum(similarities) / len(similarities), 6),
        "runtime": dict(runtime),
    }


def _runtime_metrics(
    *,
    torch: Any,
    load_seconds: float,
    elapsed_seconds: float,
    generated_tokens: int,
    records: int,
) -> dict[str, Any]:
    return {
        "precision": "bf16",
        "decoding": "greedy",
        "model_load_seconds": round(load_seconds, 3),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "seconds_per_record": round(elapsed_seconds / records, 4),
        "peak_cuda_memory_mib": round(torch.cuda.max_memory_allocated() / (1024**2), 3),
        "generated_tokens": generated_tokens,
        "generated_tokens_per_second": round(generated_tokens / elapsed_seconds, 3)
        if elapsed_seconds
        else 0.0,
    }


def evaluate_router_conditions(
    *,
    model_path: Path,
    adapter_path: Path | None,
    dataset_path: Path,
    few_shot_path: Path,
    output_root: Path,
    conditions: Sequence[Condition],
    batch_size: int = 8,
    max_new_tokens: int = 640,
) -> dict[str, Any]:
    import torch

    rows = load_jsonl(dataset_path)
    few_shot = _load_few_shot(few_shot_path)
    input_contract = {
        "dataset_path": str(dataset_path),
        "dataset_sha256": sha256_file(dataset_path),
        "few_shot_path": str(few_shot_path),
        "few_shot_sha256": sha256_file(few_shot_path),
    }
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    load_started = time.perf_counter()
    processor, model = _load_runtime(model_path, adapter_path, precision="bf16")
    load_seconds = time.perf_counter() - load_started
    results: dict[str, Any] = {}
    try:
        for condition in conditions:
            started = time.perf_counter()
            raw_rows: list[dict[str, Any]] = []
            projected_rows: list[dict[str, Any]] = []
            generated_tokens = 0
            for start in range(0, len(rows), batch_size):
                batch = rows[start : start + batch_size]
                inputs = [
                    _input_messages(
                        row,
                        task="router",
                        condition=condition,
                        few_shot=few_shot,
                    )
                    for row in batch
                ]
                generated_batch = _generate_batch(
                    processor, model, inputs, max_new_tokens=max_new_tokens
                )
                for row, messages, generated in zip(
                    batch, inputs, generated_batch, strict=True
                ):
                    generated_tokens += len(
                        processor.tokenizer.encode(generated, add_special_tokens=False)
                    )
                    raw_parsed = _strict_json(generated)
                    projected_text, projected_parsed, constraint = (
                        _decode_generated_output(
                            generated,
                            [messages[0], messages[-1]],
                            constrained_decoding=True,
                            deterministic_argument_protection=True,
                        )
                    )
                    common = {
                        "example_id": row["example_id"],
                        "task_family": row["task_family"],
                        "challenge_kind": row.get("challenge_kind"),
                        "expected": row["assistant_target"],
                    }
                    raw_rows.append(
                        common
                        | {
                            "generated": generated,
                            "parsed": raw_parsed,
                            "scores": _router_scores(row, raw_parsed),
                        }
                    )
                    projected_rows.append(
                        common
                        | {
                            "generated": projected_text,
                            "raw_generated": generated,
                            "parsed": projected_parsed,
                            "constraint": constraint,
                            "scores": _router_scores(row, projected_parsed),
                        }
                    )
                _report_progress(
                    task="router",
                    condition=condition,
                    completed=min(start + len(batch), len(rows)),
                    total=len(rows),
                )
            elapsed = time.perf_counter() - started
            runtime = _runtime_metrics(
                torch=torch,
                load_seconds=load_seconds,
                elapsed_seconds=elapsed,
                generated_tokens=generated_tokens,
                records=len(rows),
            )
            condition_dir = output_root / condition
            raw_summary = _router_summary(
                raw_rows,
                model_path=model_path,
                adapter_path=adapter_path,
                condition=condition,
                projection="raw",
                runtime=runtime,
            )
            projected_summary = _router_summary(
                projected_rows,
                model_path=model_path,
                adapter_path=adapter_path,
                condition=condition,
                projection="runtime_projected",
                runtime=runtime,
            )
            raw_summary["input_contract"] = input_contract
            projected_summary["input_contract"] = input_contract
            corrections = sum(
                not bool(raw["scores"]["strict_route_pass"])
                and bool(projected["scores"]["strict_route_pass"])
                for raw, projected in zip(raw_rows, projected_rows, strict=True)
            )
            regressions = sum(
                bool(raw["scores"]["strict_route_pass"])
                and not bool(projected["scores"]["strict_route_pass"])
                for raw, projected in zip(raw_rows, projected_rows, strict=True)
            )
            modified = sum(
                bool((row.get("constraint") or {}).get("corrections"))
                for row in projected_rows
            )
            comparison = {
                "records": len(rows),
                "raw_strict_rate": raw_summary["metrics"]["strict_route_pass"]["rate"],
                "projected_strict_rate": projected_summary["metrics"][
                    "strict_route_pass"
                ]["rate"],
                "projection_rescues": corrections,
                "projection_regressions": regressions,
                "projection_modified_records": modified,
                "projection_correction_rate": round(corrections / len(rows), 6),
                "projection_guardrail_activation_rate": round(modified / len(rows), 6),
            }
            _write_jsonl(condition_dir / "raw/predictions.jsonl", raw_rows)
            _write_json(condition_dir / "raw/summary.json", raw_summary)
            _write_jsonl(condition_dir / "normalized/predictions.jsonl", projected_rows)
            _write_json(condition_dir / "normalized/summary.json", projected_summary)
            _write_json(condition_dir / "projection_comparison.json", comparison)
            results[condition] = {
                "raw": raw_summary,
                "normalized": projected_summary,
                "projection_comparison": comparison,
            }
    finally:
        del model
        del processor
        gc.collect()
        torch.cuda.empty_cache()
    _write_json(output_root / "evaluation_index.json", results)
    return results


def evaluate_tutor_conditions(
    *,
    model_path: Path,
    adapter_path: Path | None,
    dataset_path: Path,
    few_shot_path: Path,
    output_root: Path,
    conditions: Sequence[Condition],
    batch_size: int = 4,
    max_new_tokens: int = 768,
) -> dict[str, Any]:
    import torch

    rows = load_jsonl(dataset_path)
    few_shot = _load_few_shot(few_shot_path)
    input_contract = {
        "dataset_path": str(dataset_path),
        "dataset_sha256": sha256_file(dataset_path),
        "few_shot_path": str(few_shot_path),
        "few_shot_sha256": sha256_file(few_shot_path),
    }
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    load_started = time.perf_counter()
    processor, model = _load_runtime(model_path, adapter_path, precision="bf16")
    load_seconds = time.perf_counter() - load_started
    results: dict[str, Any] = {}
    try:
        for condition in conditions:
            started = time.perf_counter()
            predictions: list[dict[str, Any]] = []
            generated_tokens = 0
            for start in range(0, len(rows), batch_size):
                batch = rows[start : start + batch_size]
                inputs = [
                    _input_messages(
                        row,
                        task="tutor",
                        condition=condition,
                        few_shot=few_shot,
                    )
                    for row in batch
                ]
                generated_batch = _generate_batch(
                    processor, model, inputs, max_new_tokens=max_new_tokens
                )
                for row, generated in zip(batch, generated_batch, strict=True):
                    generated_tokens += len(
                        processor.tokenizer.encode(generated, add_special_tokens=False)
                    )
                    parsed = _strict_json(generated)
                    predictions.append(
                        {
                            "example_id": row["example_id"],
                            "task_family": row["task_family"],
                            "challenge_kind": row.get("challenge_kind"),
                            "expected": row["assistant_target"],
                            "generated": generated,
                            "parsed": parsed,
                            "scores": _tutor_scores(row, parsed, generated),
                        }
                    )
                _report_progress(
                    task="tutor",
                    condition=condition,
                    completed=min(start + len(batch), len(rows)),
                    total=len(rows),
                )
            elapsed = time.perf_counter() - started
            runtime = _runtime_metrics(
                torch=torch,
                load_seconds=load_seconds,
                elapsed_seconds=elapsed,
                generated_tokens=generated_tokens,
                records=len(rows),
            )
            summary = _tutor_summary(
                predictions,
                model_path=model_path,
                adapter_path=adapter_path,
                condition=condition,
                runtime=runtime,
            )
            summary["input_contract"] = input_contract
            condition_dir = output_root / condition / "raw"
            _write_jsonl(condition_dir / "predictions.jsonl", predictions)
            _write_json(condition_dir / "summary.json", summary)
            results[condition] = summary
    finally:
        del model
        del processor
        gc.collect()
        torch.cuda.empty_cache()
    _write_json(output_root / "evaluation_index.json", results)
    return results


def _conditions(value: str) -> list[Condition]:
    allowed = {"base", "prompt", "few_shot", "sft"}
    result = [item.strip() for item in value.split(",") if item.strip()]
    invalid = set(result) - allowed
    if invalid:
        raise ValueError(f"unsupported conditions: {sorted(invalid)}")
    return result  # type: ignore[return-value]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=("router", "tutor"))
    parser.add_argument("--model", type=Path)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--few-shot", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--conditions", default="prompt")
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--max-new-tokens", type=int)
    args = parser.parse_args()
    paths = ControlledPaths()
    conditions = _conditions(args.conditions)
    if "sft" in conditions and args.adapter is None:
        parser.error("the sft condition requires --adapter")
    if args.task == "router":
        result = evaluate_router_conditions(
            model_path=args.model or ROUTER_MODEL,
            adapter_path=args.adapter,
            dataset_path=args.dataset or paths.router_challenge,
            few_shot_path=args.few_shot or paths.router_few_shot,
            output_root=args.output_root,
            conditions=conditions,
            batch_size=args.batch_size or 8,
            max_new_tokens=args.max_new_tokens or 640,
        )
    else:
        result = evaluate_tutor_conditions(
            model_path=args.model or TUTOR_MODEL,
            adapter_path=args.adapter,
            dataset_path=args.dataset or paths.tutor_challenge,
            few_shot_path=args.few_shot or paths.tutor_few_shot,
            output_root=args.output_root,
            conditions=conditions,
            batch_size=args.batch_size or 4,
            max_new_tokens=args.max_new_tokens or 768,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
