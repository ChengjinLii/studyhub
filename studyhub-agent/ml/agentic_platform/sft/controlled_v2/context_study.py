"""Build and run one-factor Tutor context-density and output-budget studies."""

from __future__ import annotations

import argparse
import copy
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..spec import canonical_json, load_jsonl, sha256_file
from .configs import TUTOR_MODEL
from .contract import ControlledPaths
from .evaluate import evaluate_tutor_conditions
from .prepare import _observation_evidence

CHUNK_COUNTS = (1, 3, 5, 8)
TOKEN_BUCKETS = (2048, 4096, 8192)
ANCHOR_ITEMS_PER_FAMILY = 10


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


def _completed_evaluation(
    *, output_root: Path, dataset_path: Path
) -> dict[str, Any] | None:
    summary_path = output_root / "sft/raw/summary.json"
    predictions_path = output_root / "sft/raw/predictions.jsonl"
    if not summary_path.is_file() or not predictions_path.is_file():
        return None
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        predictions = load_jsonl(predictions_path)
    except (json.JSONDecodeError, OSError, ValueError):
        return None
    if (
        summary.get("task") != "tutor"
        or summary.get("condition") != "sft"
        or int(summary.get("records", -1)) != len(predictions)
        or summary.get("input_contract", {}).get("dataset_sha256")
        != sha256_file(dataset_path)
    ):
        return None
    return summary


def _anchors(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["task_family"])].append(row)
    return [
        copy.deepcopy(row)
        for family in sorted(grouped)
        for row in grouped[family][:ANCHOR_ITEMS_PER_FAMILY]
    ]


def _payload(row: Mapping[str, Any]) -> dict[str, Any]:
    message = next(item for item in row["messages"] if item["role"] == "user")
    return json.loads(str(message["content"]))


def _set_payload(row: dict[str, Any], payload: Mapping[str, Any]) -> None:
    message = next(item for item in row["messages"] if item["role"] == "user")
    message["content"] = canonical_json(payload)


def _replace_evidence(payload: dict[str, Any], evidence: list[dict[str, Any]]) -> None:
    for observation in payload["tool_observations"]:
        result = observation.get("result") or {}
        if "evidence" in result:
            result["evidence"] = evidence
            return
    payload["tool_observations"].append(
        {
            "tool": "read_pdf_evidence",
            "result": {"available": True, "evidence": evidence},
        }
    )


def _render_tokens(processor: Any, row: Mapping[str, Any]) -> int:
    system = next(item for item in row["messages"] if item["role"] == "system")
    user = next(item for item in row["messages"] if item["role"] == "user")
    rendered = processor.apply_chat_template(
        [
            {"role": "system", "content": system["content"]},
            {"role": "user", "content": user["content"]},
        ],
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    return len(processor.tokenizer.encode(rendered, add_special_tokens=False))


def build_context_study(
    *, paths: ControlledPaths | None = None, processor: Any | None = None
) -> dict[str, Any]:
    if processor is None:
        from transformers import AutoProcessor

        processor = AutoProcessor.from_pretrained(
            TUTOR_MODEL, trust_remote_code=True, local_files_only=True
        )
    paths = paths or ControlledPaths()
    challenge = load_jsonl(paths.tutor_challenge)
    anchors = _anchors(challenge)
    evidence_pool = [
        copy.deepcopy(item) for row in challenge for item in _observation_evidence(row)
    ]
    root = paths.evaluation_root / "t-context/datasets"
    datasets: dict[str, Any] = {}

    for count in CHUNK_COUNTS:
        built: list[dict[str, Any]] = []
        for index, source in enumerate(anchors):
            row = copy.deepcopy(source)
            payload = _payload(row)
            primary = _observation_evidence(row)[:1]
            distractors = [
                copy.deepcopy(evidence_pool[(index * 17 + offset) % len(evidence_pool)])
                for offset in range(1, count)
            ]
            for offset, item in enumerate(distractors, start=1):
                item["chunk_id"] = f"context:distractor:{count}:{index}:{offset}"
                item["evidence_id"] = item["chunk_id"]
                item["text"] = "上下文密度实验的无关片段。" + str(
                    item.get("text") or ""
                )
            _replace_evidence(payload, [*primary, *distractors])
            _set_payload(row, payload)
            row["context_study"] = {"factor": "chunk_count", "value": count}
            built.append(row)
        path = root / f"chunks_{count}.jsonl"
        _write_jsonl(path, built)
        datasets[f"chunks_{count}"] = {
            "path": str(path),
            "sha256": sha256_file(path),
            "records": len(built),
        }

    padding_unit = "该段是无关上下文填充，不支持问题结论，也不应被引用。"
    for target in TOKEN_BUCKETS:
        built = []
        lengths: list[int] = []
        for source in anchors:
            row = copy.deepcopy(source)
            payload = _payload(row)
            payload["context_stress_padding"] = ""
            _set_payload(row, payload)
            current = _render_tokens(processor, row)
            if current < target:
                estimated_repeats = max(1, (target - current) // 20)
                payload["context_stress_padding"] = padding_unit * estimated_repeats
                _set_payload(row, payload)
                current = _render_tokens(processor, row)
                while current < target - 32:
                    payload["context_stress_padding"] += padding_unit * 4
                    _set_payload(row, payload)
                    current = _render_tokens(processor, row)
            row["context_study"] = {"factor": "input_tokens", "value": target}
            built.append(row)
            lengths.append(current)
        path = root / f"tokens_{target}.jsonl"
        _write_jsonl(path, built)
        datasets[f"tokens_{target}"] = {
            "path": str(path),
            "sha256": sha256_file(path),
            "records": len(built),
            "actual_tokens": {
                "min": min(lengths),
                "mean": round(sum(lengths) / len(lengths), 3),
                "max": max(lengths),
            },
        }
    manifest = {
        "schema_version": "studyhub.agent.sft.controlled_v2.context_datasets.v1",
        "one_factor_at_a_time": True,
        "anchor_records": len(anchors),
        "chunk_counts": list(CHUNK_COUNTS),
        "token_buckets": list(TOKEN_BUCKETS),
        "output_budgets": [768, 1024],
        "datasets": datasets,
        "training_eligible": False,
        "sealed_test_read": False,
    }
    _write_json(root / "manifest.json", manifest)
    return manifest


def run_context_study(
    *,
    adapter_path: Path,
    output_root: Path,
    paths: ControlledPaths | None = None,
) -> dict[str, Any]:
    paths = paths or ControlledPaths()
    manifest_path = paths.evaluation_root / "t-context/datasets/manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.is_file()
        else build_context_study(paths=paths)
    )
    results: dict[str, Any] = {}
    for label, value in manifest["datasets"].items():
        dataset_path = Path(value["path"])
        if sha256_file(dataset_path) != value["sha256"]:
            raise ValueError(f"context dataset hash changed: {dataset_path}")
        destination = output_root / label / "output_768"
        completed = _completed_evaluation(
            output_root=destination, dataset_path=dataset_path
        )
        if completed is None:
            completed = evaluate_tutor_conditions(
                model_path=TUTOR_MODEL,
                adapter_path=adapter_path,
                dataset_path=dataset_path,
                few_shot_path=paths.tutor_few_shot,
                output_root=destination,
                conditions=("sft",),
                max_new_tokens=768,
            )["sft"]
        results[f"{label}_output_768"] = completed
    token_dataset = Path(manifest["datasets"]["tokens_4096"]["path"])
    token_destination = output_root / "tokens_4096/output_1024"
    completed_1024 = _completed_evaluation(
        output_root=token_destination, dataset_path=token_dataset
    )
    if completed_1024 is None:
        completed_1024 = evaluate_tutor_conditions(
            model_path=TUTOR_MODEL,
            adapter_path=adapter_path,
            dataset_path=token_dataset,
            few_shot_path=paths.tutor_few_shot,
            output_root=token_destination,
            conditions=("sft",),
            max_new_tokens=1024,
        )["sft"]
    results["tokens_4096_output_1024"] = completed_1024
    _write_json(output_root / "context_study_index.json", results)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("build")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--adapter", type=Path, required=True)
    run_parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        result = build_context_study()
    else:
        result = run_context_study(
            adapter_path=args.adapter, output_root=args.output_root
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
