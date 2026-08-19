"""Build and validate the human-review packets required by controlled-v2."""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..spec import load_jsonl, sha256_file
from .contract import ControlledPaths

CHALLENGE_FIELDS = (
    "review_id",
    "example_id",
    "task_family",
    "current_user_query",
    "evidence_json",
    "teacher_target_json",
    "evidence_support",
    "citation_correct",
    "boundary_correct",
    "review_status",
    "notes",
    "reviewer",
    "reviewed_at",
)
FINAL_FIELDS = (
    "review_id",
    "example_id",
    "task_family",
    "current_user_query",
    "evidence_json",
    "generated_answer_json",
    "reviewer_a_correctness",
    "reviewer_a_faithfulness",
    "reviewer_a_readability",
    "reviewer_a",
    "reviewer_a_at",
    "reviewer_b_correctness",
    "reviewer_b_faithfulness",
    "reviewer_b_readability",
    "reviewer_b",
    "reviewer_b_at",
    "adjudicated_correctness",
    "adjudicated_faithfulness",
    "adjudicated_readability",
    "adjudicator",
    "adjudicated_at",
    "notes",
)
HIGH_RISK_FAMILIES = {
    "no_answer_v2",
    "conflict_v2",
    "citation_counterfactual_v2",
}
PASS_FAIL = {"pass", "fail"}
REVIEW_STATUS = {"approved", "rejected", "needs_revision"}
CHALLENGE_RUBRIC = {
    "schema_version": "studyhub.agent.sft.controlled_v2.challenge_review_rubric.v1",
    "decision_values": ["pass", "fail"],
    "dimensions": {
        "evidence_support": {
            "pass": (
                "Every substantive claim in teacher_target_json is supported by "
                "evidence_json, or the target correctly abstains when support is absent."
            ),
            "fail": (
                "The target adds unsupported claims, misses material conflict, or answers "
                "beyond the supplied evidence."
            ),
        },
        "citation_correct": {
            "pass": (
                "Every cited material_id, page, and chunk_id exists in evidence_json and "
                "supports the associated claim; an abstention may cite no source."
            ),
            "fail": (
                "A citation is missing, fabricated, mismatched, or attached to an "
                "unsupported claim."
            ),
        },
        "boundary_correct": {
            "pass": (
                "The target follows the family boundary for normal, no-answer, distractor, "
                "conflict, partial-evidence, or counterfactual-citation cases."
            ),
            "fail": (
                "The target ignores the required abstention, conflict disclosure, partial "
                "answer limit, or counterfactual citation correction."
            ),
        },
    },
    "review_status": {
        "approved": "All three dimensions pass without required edits.",
        "needs_revision": "The item is usable after a specific target or evidence correction.",
        "rejected": "The item is malformed, ambiguous, or unsuitable for this challenge.",
    },
    "coverage": {
        "high_risk_families": sorted(HIGH_RISK_FAMILIES),
        "high_risk_policy": "review every record",
        "other_families_policy": "stratified sample already selected in the frozen packet",
    },
}
FINAL_RUBRIC = {
    "schema_version": "studyhub.agent.sft.controlled_v2.final_review_rubric.v1",
    "decision_values": ["pass", "fail"],
    "dimensions": {
        "correctness": {
            "pass": "The answer correctly addresses the user request and evidence condition.",
            "fail": "The answer is factually or procedurally incorrect, incomplete, or malformed.",
        },
        "faithfulness": {
            "pass": (
                "All substantive claims are entailed by evidence_json and all citations "
                "identify supporting evidence exactly."
            ),
            "fail": (
                "The answer contains an unsupported claim, misses a required abstention or "
                "conflict disclosure, or uses an incorrect citation."
            ),
        },
        "readability": {
            "pass": (
                "The answer is complete, coherent, untruncated, and gives a usable learning "
                "explanation or boundary response."
            ),
            "fail": "The answer is confusing, truncated, internally inconsistent, or unusable.",
        },
    },
    "reviewers": {
        "independent_reviews": 2,
        "reviewer_identity_required": True,
        "model_identity_hidden": True,
        "disagreement_adjudication": (
            "A third reviewer who is neither reviewer_a nor reviewer_b records all three "
            "adjudicated decisions."
        ),
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(
    path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _payload_evidence(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for observation in payload.get("tool_observations", []):
        evidence.extend((observation.get("result") or {}).get("evidence") or [])
    return evidence


def _frozen_rows(
    rows: Sequence[Mapping[str, Any]], fields: Sequence[str]
) -> list[dict[str, Any]]:
    return [{field: row.get(field, "") for field in fields} for row in rows]


def _validate_frozen_rows(
    *,
    review_rows: Sequence[Mapping[str, str]],
    frozen_rows: Sequence[Mapping[str, Any]],
    fields: Sequence[str],
) -> list[str]:
    errors: list[str] = []
    review_ids = [str(row.get("example_id") or "") for row in review_rows]
    frozen_ids = [str(row.get("example_id") or "") for row in frozen_rows]
    if len(set(review_ids)) != len(review_ids):
        errors.append("review CSV contains duplicate example_id values")
    if set(review_ids) != set(frozen_ids) or len(review_ids) != len(frozen_ids):
        errors.append("review CSV example IDs differ from the frozen review packet")
        return errors
    frozen_by_id = {str(row["example_id"]): row for row in frozen_rows}
    for row in review_rows:
        example_id = str(row.get("example_id") or "")
        expected = frozen_by_id[example_id]
        for field in fields:
            if str(row.get(field) or "") != str(expected.get(field) or ""):
                errors.append(f"{example_id}: frozen field changed: {field}")
    return errors


def build_challenge_review(
    *, paths: ControlledPaths | None = None
) -> dict[str, Any]:
    paths = paths or ControlledPaths()
    source = paths.contract_dir / "tutor_human_review_packet_v2.jsonl"
    source_rows = load_jsonl(source)
    output_dir = paths.contract_dir / "human_review"
    csv_path = output_dir / "tutor_challenge_review_v2.csv"
    rows = []
    for index, item in enumerate(source_rows, start=1):
        payload = item["user_payload"]
        rows.append(
            {
                "review_id": f"challenge_{index:04d}",
                "example_id": item["example_id"],
                "task_family": item["task_family"],
                "current_user_query": payload.get("current_user_query", ""),
                "evidence_json": json.dumps(
                    _payload_evidence(payload), ensure_ascii=False, sort_keys=True
                ),
                "teacher_target_json": json.dumps(
                    item["teacher_target"], ensure_ascii=False, sort_keys=True
                ),
                "evidence_support": "",
                "citation_correct": "",
                "boundary_correct": "",
                "review_status": "",
                "notes": "",
                "reviewer": "",
                "reviewed_at": "",
            }
        )
    frozen_path = output_dir / "tutor_challenge_review_packet_frozen.jsonl"
    rubric_path = output_dir / "challenge_review_rubric.json"
    _write_jsonl(frozen_path, _frozen_rows(rows, CHALLENGE_FIELDS[:6]))
    _write_json(rubric_path, CHALLENGE_RUBRIC)
    _write_csv(csv_path, rows, CHALLENGE_FIELDS)
    family_counts = Counter(str(item["task_family"]) for item in source_rows)
    manifest = {
        "schema_version": "studyhub.agent.sft.controlled_v2.challenge_review.v1",
        "generated_at": _now(),
        "source_packet": str(source),
        "source_packet_sha256": sha256_file(source),
        "review_csv": str(csv_path),
        "review_csv_sha256_at_creation": sha256_file(csv_path),
        "frozen_packet": str(frozen_path),
        "frozen_packet_sha256": sha256_file(frozen_path),
        "review_rubric": str(rubric_path),
        "review_rubric_sha256": sha256_file(rubric_path),
        "records": len(rows),
        "family_counts": dict(sorted(family_counts.items())),
        "high_risk_families": sorted(HIGH_RISK_FAMILIES),
        "high_risk_records": sum(
            count
            for family, count in family_counts.items()
            if family in HIGH_RISK_FAMILIES
        ),
        "human_review_completed": False,
    }
    _write_json(output_dir / "challenge_review_manifest.json", manifest)
    return manifest


def validate_challenge_review(
    *, review_csv: Path, paths: ControlledPaths | None = None
) -> dict[str, Any]:
    paths = paths or ControlledPaths()
    rows = _read_csv(review_csv)
    errors: list[str] = []
    manifest_path = paths.contract_dir / "human_review/challenge_review_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_path = paths.contract_dir / "tutor_human_review_packet_v2.jsonl"
    frozen_path = Path(str(manifest["frozen_packet"]))
    rubric_path = Path(str(manifest["review_rubric"]))
    if sha256_file(source_path) != manifest["source_packet_sha256"]:
        errors.append("challenge source packet changed after review packet creation")
    if sha256_file(frozen_path) != manifest["frozen_packet_sha256"]:
        errors.append("challenge frozen review packet changed after creation")
    if sha256_file(rubric_path) != manifest["review_rubric_sha256"]:
        errors.append("challenge review rubric changed after packet creation")
    frozen_rows = load_jsonl(frozen_path)
    errors.extend(
        _validate_frozen_rows(
            review_rows=rows,
            frozen_rows=frozen_rows,
            fields=CHALLENGE_FIELDS[:6],
        )
    )
    approved = 0
    high_risk_reviewed = Counter()
    reviewers = set()
    for row in rows:
        review_id = row.get("review_id") or "unknown"
        decisions = {
            key: str(row.get(key) or "").strip().lower()
            for key in ("evidence_support", "citation_correct", "boundary_correct")
        }
        status = str(row.get("review_status") or "").strip().lower()
        reviewer = str(row.get("reviewer") or "").strip()
        reviewed_at = str(row.get("reviewed_at") or "").strip()
        for key, value in decisions.items():
            if value not in PASS_FAIL:
                errors.append(f"{review_id}: {key} must be pass or fail")
        if status not in REVIEW_STATUS:
            errors.append(f"{review_id}: invalid review_status")
        if not reviewer:
            errors.append(f"{review_id}: reviewer is required")
        else:
            reviewers.add(reviewer)
        if not reviewed_at:
            errors.append(f"{review_id}: reviewed_at is required")
        row_approved = status == "approved" and all(
            value == "pass" for value in decisions.values()
        )
        approved += int(row_approved)
        family = str(row.get("task_family") or "")
        if family in HIGH_RISK_FAMILIES and not any(
            error.startswith(f"{review_id}:") for error in errors
        ):
            high_risk_reviewed[family] += 1
    family_counts = Counter(str(row.get("task_family") or "") for row in rows)
    high_risk_complete = all(
        high_risk_reviewed[family] == family_counts[family]
        and family_counts[family] > 0
        for family in HIGH_RISK_FAMILIES
    )
    result = {
        "schema_version": "studyhub.agent.sft.controlled_v2.challenge_review_receipt.v1",
        "validated_at": _now(),
        "review_csv": str(review_csv),
        "review_csv_sha256": sha256_file(review_csv),
        "review_manifest": str(manifest_path),
        "review_manifest_sha256": sha256_file(manifest_path),
        "frozen_packet": str(frozen_path),
        "frozen_packet_sha256": sha256_file(frozen_path),
        "review_rubric": str(rubric_path),
        "review_rubric_sha256": sha256_file(rubric_path),
        "source_packet": str(source_path),
        "source_packet_sha256": sha256_file(source_path),
        "records": len(rows),
        "approved_records": approved,
        "reviewers": sorted(reviewers),
        "errors": errors,
        "human_review_completed": bool(rows) and not errors,
        "all_records_approved": bool(rows) and approved == len(rows) and not errors,
        "high_risk_full_review_completed": high_risk_complete and not errors,
        "family_counts": dict(sorted(family_counts.items())),
    }
    destination = paths.contract_dir / "human_review/challenge_review_receipt.json"
    _write_json(destination, result)
    return result


def _final_review_sources(paths: ControlledPaths) -> tuple[dict[str, Any], Path]:
    decision_path = paths.evaluation_root / "final/tutor/final_decision.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    if not decision.get("passed"):
        raise RuntimeError("Tutor development decision must pass before blind review")
    prediction_path = (
        paths.evaluation_root
        / str(decision["experiment_id"])
        / str(decision["delivery_seed"])
        / "sft/raw/predictions.jsonl"
    )
    return decision, prediction_path


def build_final_review(
    *, paths: ControlledPaths | None = None, seed: int = 20260816
) -> dict[str, Any]:
    paths = paths or ControlledPaths()
    _decision, prediction_path = _final_review_sources(paths)
    predictions = load_jsonl(prediction_path)
    challenge = {
        str(item["example_id"]): item for item in load_jsonl(paths.tutor_challenge)
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in predictions:
        grouped[str(item["task_family"])].append(item)
    rng = random.Random(seed)
    selected = []
    for family in sorted(grouped):
        values = sorted(grouped[family], key=lambda item: str(item["example_id"]))
        rng.shuffle(values)
        if len(values) < 20:
            raise ValueError(f"{family} has fewer than 20 final-review candidates")
        selected.extend(values[:20])
    if len(selected) != 120:
        raise ValueError(f"final blind review requires 120 rows, found {len(selected)}")

    rows = []
    for index, prediction in enumerate(selected, start=1):
        example_id = str(prediction["example_id"])
        source = challenge[example_id]
        user_message = next(
            item for item in source["messages"] if item["role"] == "user"
        )
        payload = json.loads(str(user_message["content"]))
        rows.append(
            {
                "review_id": f"blind_{index:04d}",
                "example_id": example_id,
                "task_family": prediction["task_family"],
                "current_user_query": payload.get("current_user_query", ""),
                "evidence_json": json.dumps(
                    _payload_evidence(payload), ensure_ascii=False, sort_keys=True
                ),
                "generated_answer_json": prediction["generated"],
                **{field: "" for field in FINAL_FIELDS[6:]},
            }
        )
    output_dir = paths.evaluation_root / "final/human_review"
    csv_path = output_dir / "tutor_final_blind_review.csv"
    frozen_path = output_dir / "tutor_final_blind_packet.jsonl"
    rubric_path = output_dir / "final_review_rubric.json"
    _write_jsonl(frozen_path, _frozen_rows(rows, FINAL_FIELDS[:6]))
    _write_json(rubric_path, FINAL_RUBRIC)
    _write_csv(csv_path, rows, FINAL_FIELDS)
    manifest = {
        "schema_version": "studyhub.agent.sft.controlled_v2.final_review.v1",
        "generated_at": _now(),
        "blinded": True,
        "sampling_seed": seed,
        "records": len(rows),
        "records_per_family": 20,
        "family_counts": dict(
            sorted(Counter(str(item["task_family"]) for item in selected).items())
        ),
        "prediction_source": str(prediction_path),
        "prediction_source_sha256": sha256_file(prediction_path),
        "development_decision": str(
            paths.evaluation_root / "final/tutor/final_decision.json"
        ),
        "development_decision_sha256": sha256_file(
            paths.evaluation_root / "final/tutor/final_decision.json"
        ),
        "review_csv": str(csv_path),
        "review_csv_sha256_at_creation": sha256_file(csv_path),
        "frozen_packet": str(frozen_path),
        "frozen_packet_sha256": sha256_file(frozen_path),
        "review_rubric": str(rubric_path),
        "review_rubric_sha256": sha256_file(rubric_path),
        "model_identity_exposed_in_review_csv": False,
        "completed": False,
    }
    _write_json(output_dir / "final_review_manifest.json", manifest)
    return manifest


def _decision(row: Mapping[str, str], prefix: str, metric: str) -> str:
    return str(row.get(f"{prefix}_{metric}") or "").strip().lower()


def validate_final_review(
    *, review_csv: Path, paths: ControlledPaths | None = None
) -> dict[str, Any]:
    paths = paths or ControlledPaths()
    rows = _read_csv(review_csv)
    errors: list[str] = []
    manifest_path = paths.evaluation_root / "final/human_review/final_review_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    prediction_path = Path(str(manifest["prediction_source"]))
    decision_path = Path(str(manifest["development_decision"]))
    frozen_path = Path(str(manifest["frozen_packet"]))
    rubric_path = Path(str(manifest["review_rubric"]))
    if sha256_file(prediction_path) != manifest["prediction_source_sha256"]:
        errors.append("final-review prediction source changed after packet creation")
    if sha256_file(decision_path) != manifest["development_decision_sha256"]:
        errors.append("Tutor development decision changed after packet creation")
    if sha256_file(frozen_path) != manifest["frozen_packet_sha256"]:
        errors.append("final frozen review packet changed after creation")
    if sha256_file(rubric_path) != manifest["review_rubric_sha256"]:
        errors.append("final review rubric changed after packet creation")
    frozen_rows = load_jsonl(frozen_path)
    errors.extend(
        _validate_frozen_rows(
            review_rows=rows,
            frozen_rows=frozen_rows,
            fields=FINAL_FIELDS[:6],
        )
    )
    family_counts = Counter(str(item.get("task_family") or "") for item in rows)
    if len(rows) != 120 or set(family_counts.values()) != {20}:
        errors.append("final review must contain exactly 20 rows from each of 6 families")
    approved = 0
    disagreement_rows = 0
    adjudicated_rows = 0
    reviewers = set()
    adjudicators = set()
    metrics = ("correctness", "faithfulness", "readability")
    for row in rows:
        review_id = row.get("review_id") or "unknown"
        row_errors: list[str] = []
        for prefix in ("reviewer_a", "reviewer_b"):
            for metric in metrics:
                if _decision(row, prefix, metric) not in PASS_FAIL:
                    row_errors.append(f"{review_id}: {prefix}_{metric} is invalid")
            reviewer = str(row.get(prefix) or "").strip()
            reviewed_at = str(row.get(f"{prefix}_at") or "").strip()
            if not reviewer:
                row_errors.append(f"{review_id}: {prefix} identity is required")
            else:
                reviewers.add(reviewer)
            if not reviewed_at:
                row_errors.append(f"{review_id}: {prefix}_at is required")
        if str(row.get("reviewer_a") or "").strip() == str(
            row.get("reviewer_b") or ""
        ).strip():
            row_errors.append(f"{review_id}: reviewer_a and reviewer_b must differ")
        disagreement = any(
            _decision(row, "reviewer_a", metric)
            != _decision(row, "reviewer_b", metric)
            for metric in metrics
        )
        final_values: dict[str, str] = {}
        if disagreement:
            disagreement_rows += 1
            for metric in metrics:
                value = _decision(row, "adjudicated", metric)
                final_values[metric] = value
                if value not in PASS_FAIL:
                    row_errors.append(
                        f"{review_id}: adjudicated_{metric} is required"
                    )
            adjudicator = str(row.get("adjudicator") or "").strip()
            adjudicated_at = str(row.get("adjudicated_at") or "").strip()
            if not adjudicator:
                row_errors.append(f"{review_id}: adjudicator is required")
            else:
                adjudicators.add(adjudicator)
                if adjudicator in {
                    str(row.get("reviewer_a") or "").strip(),
                    str(row.get("reviewer_b") or "").strip(),
                }:
                    row_errors.append(
                        f"{review_id}: adjudicator must be independent"
                    )
            if not adjudicated_at:
                row_errors.append(f"{review_id}: adjudicated_at is required")
            if not row_errors:
                adjudicated_rows += 1
        else:
            final_values = {
                metric: _decision(row, "reviewer_a", metric) for metric in metrics
            }
        errors.extend(row_errors)
        approved += int(not row_errors and all(v == "pass" for v in final_values.values()))
    result = {
        "schema_version": "studyhub.agent.sft.controlled_v2.final_review_receipt.v1",
        "validated_at": _now(),
        "review_csv": str(review_csv),
        "review_csv_sha256": sha256_file(review_csv),
        "review_manifest": str(manifest_path),
        "review_manifest_sha256": sha256_file(manifest_path),
        "prediction_source": str(prediction_path),
        "prediction_source_sha256": sha256_file(prediction_path),
        "records": len(rows),
        "approved_records": approved,
        "reviewers": sorted(reviewers),
        "adjudicators": sorted(adjudicators),
        "disagreement_rows": disagreement_rows,
        "adjudicated_rows": adjudicated_rows,
        "blinded": True,
        "adjudication_completed": disagreement_rows == adjudicated_rows,
        "completed": len(rows) == 120 and not errors,
        "all_records_approved": len(rows) == 120 and approved == len(rows) and not errors,
        "errors": errors,
        "family_counts": dict(sorted(family_counts.items())),
    }
    destination = paths.evaluation_root / "final/human_review_receipt.json"
    _write_json(destination, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("build-challenge")
    challenge_validate = subparsers.add_parser("validate-challenge")
    challenge_validate.add_argument("--review-csv", type=Path, required=True)
    final_build = subparsers.add_parser("build-final")
    final_build.add_argument("--seed", type=int, default=20260816)
    final_validate = subparsers.add_parser("validate-final")
    final_validate.add_argument("--review-csv", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build-challenge":
        result = build_challenge_review()
    elif args.command == "validate-challenge":
        result = validate_challenge_review(review_csv=args.review_csv)
    elif args.command == "build-final":
        result = build_final_review(seed=args.seed)
    else:
        result = validate_final_review(review_csv=args.review_csv)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if args.command == "validate-challenge" and not (
        result.get("all_records_approved")
        and result.get("high_risk_full_review_completed")
    ):
        raise SystemExit(1)
    if args.command == "validate-final" and not (
        result.get("all_records_approved")
        and result.get("adjudication_completed")
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
