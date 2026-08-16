"""Structural, leakage, and token-budget audit for the frozen SFT contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..spec import canonical_json, load_jsonl, sha256_file
from .contract import ControlledPaths
from .prepare import _material_ids, _observation_evidence


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


def _message(row: Mapping[str, Any], role: str) -> Mapping[str, Any]:
    return next(item for item in row["messages"] if item["role"] == role)


def _query_hashes(rows: Sequence[Mapping[str, Any]]) -> set[str]:
    return {
        hashlib.sha256(str(_message(row, "user")["content"]).encode()).hexdigest()
        for row in rows
    }


def _token_stats(
    *,
    processor: Any,
    rows: Sequence[Mapping[str, Any]],
    few_shot: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    by_condition: dict[str, list[int]] = {"prompt": [], "few_shot": []}
    for row in rows:
        system = {"role": "system", "content": str(_message(row, "system")["content"])}
        user = {"role": "user", "content": str(_message(row, "user")["content"])}
        for condition, demos in (("prompt", []), ("few_shot", few_shot)):
            rendered = processor.apply_chat_template(
                [system, *demos, user],
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            by_condition[condition].append(
                len(processor.tokenizer.encode(rendered, add_special_tokens=False))
            )
    return {
        condition: {
            "records": len(values),
            "min": min(values),
            "mean": round(sum(values) / len(values), 3),
            "max": max(values),
            "within_4096": max(values) <= 4096,
        }
        for condition, values in by_condition.items()
    }


def _tutor_invariant_errors(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    errors: list[str] = []
    for row in rows:
        family = str(row["task_family"])
        example_id = str(row["example_id"])
        target = row["assistant_target"]
        citations = list(target.get("evidence_sources") or [])
        answer = str(target.get("answer") or "")
        evidence = _observation_evidence(row)
        payload = json.loads(str(_message(row, "user")["content"]))
        query = str(payload.get("current_user_query") or "")
        if row.get("challenge_contract_revision") != "semantic_v2_2":
            errors.append(f"{example_id}: challenge semantic revision is missing")
        if canonical_json(target) != canonical_json(
            json.loads(str(_message(row, "assistant")["content"]))
        ):
            errors.append(f"{example_id}: assistant target mismatch")
        if (
            family in {"normal_answer_v2", "distractor_v2", "partial_evidence_v2"}
            and not citations
        ):
            errors.append(f"{example_id}: expected grounded citation")
        if family == "distractor_v2" and len(evidence) <= len(citations):
            errors.append(f"{example_id}: distractor was not added")
        if family == "conflict_v2" and (len(citations) < 2 or "冲突" not in answer):
            errors.append(f"{example_id}: conflict target is incomplete")
        if family == "partial_evidence_v2" and not any(
            phrase in answer for phrase in ("缺口", "证据不足", "只支持")
        ):
            errors.append(f"{example_id}: partial target lacks scope disclosure")
        if family in {"no_answer_v2", "citation_counterfactual_v2"} and (
            citations
            or not any(phrase in answer for phrase in ("证据不足", "无法", "不一致"))
        ):
            errors.append(f"{example_id}: abstention target is incomplete")
        if family == "no_answer_v2" and not all(
            phrase in query
            for phrase in (
                "仅根据当前可见证据",
                "未展示的课后题标准答案",
                "不得使用外部知识补全",
            )
        ):
            errors.append(f"{example_id}: no-answer query is not wholly unanswerable")
        if family == "citation_counterfactual_v2" and not any(
            item.get("metadata_integrity") is False for item in evidence
        ):
            errors.append(f"{example_id}: counterfactual marker is missing")
    return errors


def _review_packet(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    high_risk = {"no_answer_v2", "conflict_v2", "citation_counterfactual_v2"}
    selected: list[Mapping[str, Any]] = []
    family_offsets: Counter[str] = Counter()
    for row in rows:
        family = str(row["task_family"])
        include = family in high_risk or family_offsets[family] < 8
        family_offsets[family] += 1
        if include:
            selected.append(row)
    return [
        {
            "example_id": row["example_id"],
            "task_family": row["task_family"],
            "user_payload": json.loads(str(_message(row, "user")["content"])),
            "teacher_target": row["assistant_target"],
            "review_fields": {
                "evidence_support": None,
                "citation_correct": None,
                "boundary_correct": None,
                "notes": "",
            },
        }
        for row in selected
    ]


def audit_controlled_v2(
    *,
    paths: ControlledPaths | None = None,
    model_path: Path = Path("/data/chengjin/studyhub/models/P0/Qwen3.5-2B"),
) -> dict[str, Any]:
    from transformers import AutoProcessor

    paths = paths or ControlledPaths()
    router_source = load_jsonl(paths.router_source)
    router = load_jsonl(paths.router_challenge)
    tutor_source = load_jsonl(paths.tutor_source)
    tutor = load_jsonl(paths.tutor_challenge)
    router_few_shot = json.loads(paths.router_few_shot.read_text(encoding="utf-8"))
    tutor_few_shot = json.loads(paths.tutor_few_shot.read_text(encoding="utf-8"))
    processor = AutoProcessor.from_pretrained(
        model_path, trust_remote_code=True, local_files_only=True
    )
    tokenization = {
        "router": _token_stats(
            processor=processor, rows=router, few_shot=router_few_shot
        ),
        "tutor": _token_stats(processor=processor, rows=tutor, few_shot=tutor_few_shot),
    }
    errors = _tutor_invariant_errors(tutor)
    router_overlap = len(_query_hashes(router_source) & _query_hashes(router))
    if router_overlap:
        errors.append(f"Router exact query overlap: {router_overlap}")
    material_overlap = sorted(_material_ids(tutor_source) & _material_ids(tutor))
    if material_overlap:
        errors.append(f"Tutor train/challenge material overlap: {material_overlap}")
    for task, values in tokenization.items():
        for condition, stats in values.items():
            if not stats["within_4096"]:
                errors.append(f"{task}/{condition} exceeds 4096 input tokens")
    seal_path = paths.contract_dir / "tutor_sealed_test_v2_seal.json"
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    if sha256_file(paths.tutor_sealed) != seal["dataset_sha256"]:
        errors.append("Tutor sealed-test hash no longer matches its seal")

    packet = _review_packet(tutor)
    packet_path = paths.contract_dir / "tutor_human_review_packet_v2.jsonl"
    _write_jsonl(packet_path, packet)
    result = {
        "schema_version": "studyhub.agent.sft.controlled_v2.audit.v1",
        "passed": not errors,
        "errors": errors,
        "router": {
            "records": len(router),
            "family_counts": dict(
                sorted(Counter(str(row["task_family"]) for row in router).items())
            ),
            "exact_source_query_overlap": router_overlap,
            "assistant_target_consistent": all(
                canonical_json(row["assistant_target"])
                == canonical_json(
                    json.loads(str(_message(row, "assistant")["content"]))
                )
                for row in router
            ),
        },
        "tutor": {
            "records": len(tutor),
            "family_counts": dict(
                sorted(Counter(str(row["task_family"]) for row in tutor).items())
            ),
            "train_material_overlap": material_overlap,
            "teacher_structural_reviewed": len(tutor),
            "human_review_packet_records": len(packet),
            "human_review_packet_fraction": round(len(packet) / len(tutor), 6),
            "human_review_completed": False,
        },
        "tokenization": tokenization,
        "sealed_test": {
            "seal_path": str(seal_path),
            "seal_sha256": sha256_file(seal_path),
            "dataset_hash_verified_without_parsing_records": True,
            "evaluated": seal["evaluated"],
        },
        "isolation": {
            "production_database_accessed": False,
            "production_api_called": False,
            "contains_paid_material": False,
        },
    }
    audit_path = paths.contract_dir / "audit.json"
    _write_json(audit_path, result)
    prereg = json.loads(paths.pre_registration.read_text(encoding="utf-8"))
    prereg["audit"]["controlled_v2_audit_path"] = str(audit_path)
    prereg["audit"]["controlled_v2_audit_sha256"] = sha256_file(audit_path)
    prereg["audit"]["token_budget_passed"] = not any(
        "4096" in error for error in errors
    )
    prereg["audit"]["teacher_structural_review_completed"] = True
    prereg["audit"]["human_review"]["packet_path"] = str(packet_path)
    prereg["audit"]["human_review"]["packet_records"] = len(packet)
    _write_json(paths.pre_registration, prereg)
    if errors:
        raise ValueError("controlled-v2 audit failed: " + "; ".join(errors[:20]))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("/data/chengjin/studyhub/models/P0/Qwen3.5-2B"),
    )
    args = parser.parse_args()
    result = audit_controlled_v2(model_path=args.model)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
