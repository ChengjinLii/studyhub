"""Build and validate a human-review packet for an isolated SFT split.

The packet never promotes teacher labels to human gold automatically. A
reviewer must fill every decision field before ``validate`` can issue a signed
completion receipt.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .spec import canonical_json, load_jsonl, sha256_file

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET = (
    PROJECT_ROOT
    / "training_artifacts/studyhub_agent_sft/router_2b_v1_4_runtime_aligned"
    / "router_tool_2b_v1_4.jsonl"
)
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT
    / "training_artifacts/studyhub_agent_sft/router_2b_v1_4_runtime_aligned"
    / "human_review"
)
REVIEW_FIELDS = (
    "review_id",
    "example_id",
    "split",
    "task_family",
    "runtime_path",
    "source_example_id",
    "current_user_query",
    "expected_mode",
    "expected_tool",
    "expected_material_ids",
    "expected_page_numbers",
    "assistant_target_json",
    "source_snapshot_id",
    "deterministic_checks_passed",
    "teacher_policy_reviewed",
    "human_review_status",
    "human_correctness",
    "human_safety",
    "human_notes",
    "reviewer",
    "reviewed_at",
)
ALLOWED_REVIEW_STATUS = {"approved", "rejected", "needs_revision"}
ALLOWED_CORRECTNESS = {"yes", "no"}
ALLOWED_SAFETY = {"pass", "fail"}


def _target_tool(target: dict[str, Any]) -> str:
    actions = target.get("actions") or []
    return str(actions[0].get("name") or "") if actions else ""


def _target_identifiers(target: dict[str, Any]) -> tuple[list[int], list[int]]:
    material_ids: set[int] = set()
    page_numbers: set[int] = set()
    for action in target.get("actions") or []:
        arguments = action.get("arguments") or {}
        material_ids.update(int(value) for value in arguments.get("material_ids") or [])
        page_numbers.update(int(value) for value in arguments.get("page_numbers") or [])
    for item in target.get("recommendations") or []:
        material_ids.add(int(item["material_id"]))
    for item in target.get("evidence_sources") or []:
        material_ids.add(int(item["material_id"]))
        if item.get("page") is not None:
            page_numbers.add(int(item["page"]))
    return sorted(material_ids), sorted(page_numbers)


def _review_row(record: dict[str, Any], review_number: int) -> dict[str, str]:
    payload = json.loads(str(record["messages"][1]["content"]))
    target = dict(record["assistant_target"])
    material_ids, page_numbers = _target_identifiers(target)
    quality = dict(record.get("quality") or {})
    remediation = dict(record.get("remediation_contract") or {})
    provenance = dict(record.get("provenance") or {})
    snapshot = dict(record.get("source_snapshot") or {})
    return {
        "review_id": f"review_{review_number:04d}",
        "example_id": str(record["example_id"]),
        "split": str(record["split"]),
        "task_family": str(record["task_family"]),
        "runtime_path": str(remediation.get("runtime_path") or ""),
        "source_example_id": str(provenance.get("source_example_id") or ""),
        "current_user_query": str(payload.get("current_user_query") or ""),
        "expected_mode": str(target.get("mode") or ""),
        "expected_tool": _target_tool(target),
        "expected_material_ids": canonical_json(material_ids),
        "expected_page_numbers": canonical_json(page_numbers),
        "assistant_target_json": canonical_json(target),
        "source_snapshot_id": str(snapshot.get("snapshot_id") or ""),
        "deterministic_checks_passed": str(
            bool(quality.get("deterministic_checks_passed"))
        ).lower(),
        "teacher_policy_reviewed": str(
            bool(quality.get("teacher_policy_reviewed"))
        ).lower(),
        "human_review_status": "",
        "human_correctness": "",
        "human_safety": "",
        "human_notes": "",
        "reviewer": "",
        "reviewed_at": "",
    }


def build_review_packet(
    *,
    dataset_path: Path = DEFAULT_DATASET,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    split: str = "validation",
    generated_at: str | None = None,
) -> dict[str, Any]:
    records = [row for row in load_jsonl(dataset_path) if row.get("split") == split]
    if not records:
        raise ValueError(f"no records found for split {split!r}")
    records.sort(key=lambda row: (str(row["task_family"]), str(row["example_id"])))
    rows = [_review_row(record, index) for index, record in enumerate(records, start=1)]

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"{split}_review.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    instructions_path = output_dir / "REVIEW_GUIDE.md"
    instructions_path.write_text(
        """# StudyHub SFT 人工复核指南

本复核包只用于离线 SFT 数据验收，不连接生产数据库、API 或 OSS。

逐行检查：用户问题与当前状态是否匹配；`mode` 和工具是否是唯一合理下一步；参数中的 `material_id`、页码与观察是否一致；最终回答是否严格受证据约束；是否拒绝越权且能安全继续只读任务；输出是否为单个合法 JSON。

填写规则：`human_review_status` 只能是 `approved`、`rejected` 或 `needs_revision`；`human_correctness` 填 `yes/no`；`human_safety` 填 `pass/fail`；同时填写 reviewer 和 ISO 8601 格式的 reviewed_at。任何拒绝或待修订项都不能计为 human gold。

完成后运行：

```bash
backend/.venv/bin/python -m ml.agentic_platform.sft.build_human_review_packet validate \\
  --review-csv <artifact_dir>/human_review/validation_review.csv
```
""",
        encoding="utf-8",
    )
    family_counts = Counter(str(record["task_family"]) for record in records)
    runtime_counts = Counter(
        runtime_path
        for record in records
        if (
            runtime_path := str(
                dict(record.get("remediation_contract") or {}).get("runtime_path")
                or ""
            )
        )
    )
    profile_counts = Counter(str(record["target_profile"]) for record in records)
    manifest = {
        "schema_version": "studyhub.agent.sft.human_review_packet.v1",
        "generated_at": generated_at
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "dataset_path": str(dataset_path),
        "dataset_sha256": sha256_file(dataset_path),
        "split": split,
        "records": len(rows),
        "family_counts": dict(sorted(family_counts.items())),
        "profile_counts": dict(sorted(profile_counts.items())),
        "runtime_path_counts": dict(sorted(runtime_counts.items())),
        "review_csv": str(csv_path),
        "review_csv_sha256": sha256_file(csv_path),
        "human_review_complete": False,
        "human_gold": False,
    }
    (output_dir / "review_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def validate_review_packet(
    *,
    review_csv: Path,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    with review_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("review CSV is empty")

    errors: list[str] = []
    for row in rows:
        review_id = str(row.get("review_id") or "unknown")
        status = str(row.get("human_review_status") or "").strip().lower()
        correctness = str(row.get("human_correctness") or "").strip().lower()
        safety = str(row.get("human_safety") or "").strip().lower()
        if status not in ALLOWED_REVIEW_STATUS:
            errors.append(f"{review_id}: invalid human_review_status")
        if correctness not in ALLOWED_CORRECTNESS:
            errors.append(f"{review_id}: invalid human_correctness")
        if safety not in ALLOWED_SAFETY:
            errors.append(f"{review_id}: invalid human_safety")
        if not str(row.get("reviewer") or "").strip():
            errors.append(f"{review_id}: reviewer is required")
        if not str(row.get("reviewed_at") or "").strip():
            errors.append(f"{review_id}: reviewed_at is required")

    approved = sum(
        str(row.get("human_review_status") or "").strip().lower() == "approved"
        and str(row.get("human_correctness") or "").strip().lower() == "yes"
        and str(row.get("human_safety") or "").strip().lower() == "pass"
        for row in rows
    )
    result = {
        "schema_version": "studyhub.agent.sft.human_review_receipt.v1",
        "validated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "review_csv": str(review_csv),
        "review_csv_sha256": sha256_file(review_csv),
        "records": len(rows),
        "approved_records": approved,
        "errors": errors,
        "human_review_complete": not errors,
        "all_records_approved": approved == len(rows) and not errors,
        "human_gold": approved == len(rows) and not errors,
    }
    destination = receipt_path or review_csv.with_name("human_review_receipt.json")
    destination.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    build_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    build_parser.add_argument("--split", default="validation")
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--review-csv", type=Path, required=True)
    validate_parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()

    if args.command == "build":
        result = build_review_packet(
            dataset_path=args.dataset,
            output_dir=args.output_dir,
            split=args.split,
        )
    else:
        result = validate_review_packet(
            review_csv=args.review_csv,
            receipt_path=args.receipt,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if args.command == "validate" and not result["human_review_complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
