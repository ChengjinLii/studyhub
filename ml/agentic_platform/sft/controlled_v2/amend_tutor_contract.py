"""Apply the pre-selection Tutor no-answer semantic contract correction."""

from __future__ import annotations

import json
import shutil
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..build_grounded_tutor_9b_v1 import DEFAULT_HOLDOUT, DEFAULT_TRANSCRIPTIONS
from ..build_validation_dataset import DEFAULT_MATERIALS_PATH
from ..spec import load_jsonl, sha256_file
from .audit import audit_controlled_v2
from .context_study import build_context_study
from .contract import (
    CONTRACT_VERSION,
    ControlledPaths,
    contract_payload,
    contract_sha256,
)
from .prepare import (
    TUTOR_ITEMS_PER_FAMILY,
    TUTOR_SEALED_ITEMS_PER_FAMILY,
    _base_rows_from_extra_transcriptions,
    _compact_tutor_few_shot,
    _material_ids,
    _page_evidence_rows,
    _tutor_pressure_dataset,
    _write_json,
    _write_jsonl,
)

AMENDMENT_ID = "tutor-no-answer-wholly-unanswerable-v2-2"


def _copy_if_present(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)


def _archive_evaluation(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    shutil.move(str(source), str(destination))


def _sealed_sources(
    *,
    tutor_source: Sequence[Mapping[str, Any]],
    tutor_holdout: Sequence[Mapping[str, Any]],
    transcriptions_path: Path,
    materials_path: Path,
    generated_at: str,
) -> list[dict[str, Any]]:
    used_material_ids = _material_ids(tutor_source) | _material_ids(tutor_holdout)
    candidates = _base_rows_from_extra_transcriptions(
        transcriptions_path=transcriptions_path,
        materials_path=materials_path,
        excluded_material_ids=used_material_ids,
        generated_at=generated_at,
    )
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        for material_id in _material_ids([row]):
            groups[material_id].append(row)
    usable_materials = sorted(
        material_id for material_id, rows in groups.items() if rows
    )
    if len(usable_materials) < 2:
        raise ValueError("Tutor sealed amendment requires at least two materials")
    selected = usable_materials[: min(6, len(usable_materials))]
    return [row for material_id in selected for row in groups[material_id]]


def amend_tutor_contract(
    *,
    paths: ControlledPaths | None = None,
    tutor_holdout_path: Path = DEFAULT_HOLDOUT,
    transcriptions_path: Path = DEFAULT_TRANSCRIPTIONS,
    materials_path: Path = DEFAULT_MATERIALS_PATH,
) -> dict[str, Any]:
    paths = paths or ControlledPaths()
    registry = json.loads(paths.experiment_registry.read_text(encoding="utf-8"))
    if registry.get("selection_events"):
        raise RuntimeError(
            "Tutor semantic amendment is forbidden after model selection"
        )
    existing = [
        item
        for item in registry.get("data_contract_amendments", [])
        if item.get("amendment_id") == AMENDMENT_ID
    ]
    receipt_path = paths.contract_dir / "semantic_v2_2_amendment_receipt.json"
    if existing:
        if receipt_path.is_file():
            return json.loads(receipt_path.read_text(encoding="utf-8"))
        audit = audit_controlled_v2(paths=paths)
        context = build_context_study(paths=paths)
        result = {
            "schema_version": CONTRACT_VERSION,
            "amendment": existing[0],
            "audit_passed": audit["passed"],
            "context_anchor_records": context["anchor_records"],
            "selection_events_before_amendment": 0,
            "resumed_after_partial_execution": True,
        }
        _write_json(receipt_path, result)
        return result

    pre_registration = json.loads(paths.pre_registration.read_text(encoding="utf-8"))
    old_seal_path = paths.contract_dir / "tutor_sealed_test_v2_seal.json"
    old_seal = json.loads(old_seal_path.read_text(encoding="utf-8"))
    if old_seal.get("evaluated"):
        raise RuntimeError("Tutor sealed data was already evaluated")

    archive = paths.contract_dir / "superseded/semantic_v2_1"
    if archive.exists():
        raise FileExistsError(archive)
    for source in (
        paths.tutor_challenge,
        paths.tutor_sealed,
        paths.tutor_few_shot,
        old_seal_path,
        paths.pre_registration,
        paths.experiment_registry,
        paths.contract_dir / "audit.json",
        paths.contract_dir / "tutor_human_review_packet_v2.jsonl",
    ):
        _copy_if_present(source, archive / source.name)

    evaluation_archive = paths.evaluation_root / "superseded/semantic_v2_1"
    for experiment_id, seed in (
        ("t-opt-r16-all-lr3e5-e1-cosine", 6209),
        ("t-opt-r16-all-lr8e5-e1-cosine", 6209),
    ):
        _archive_evaluation(
            paths.evaluation_root / experiment_id / str(seed),
            evaluation_archive / experiment_id / str(seed),
        )
    context_root = paths.evaluation_root / "t-context"
    _archive_evaluation(context_root, evaluation_archive / "t-context")

    tutor_source = load_jsonl(paths.tutor_source)
    tutor_holdout = load_jsonl(tutor_holdout_path)
    generated_at = str(pre_registration.get("generated_at") or "")
    if not generated_at:
        generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    tutor_challenge = _tutor_pressure_dataset(
        tutor_holdout,
        items_per_family=TUTOR_ITEMS_PER_FAMILY,
        split="validation",
    )
    sealed_base = _sealed_sources(
        tutor_source=tutor_source,
        tutor_holdout=tutor_holdout,
        transcriptions_path=transcriptions_path,
        materials_path=materials_path,
        generated_at=generated_at,
    )
    tutor_sealed = _tutor_pressure_dataset(
        sealed_base,
        items_per_family=TUTOR_SEALED_ITEMS_PER_FAMILY,
        split="test",
    )
    tutor_fewshot_sources = _tutor_pressure_dataset(
        _page_evidence_rows(tutor_source),
        items_per_family=1,
        split="validation",
    )
    tutor_few_shot = _compact_tutor_few_shot(tutor_fewshot_sources)

    _write_jsonl(paths.tutor_challenge, tutor_challenge)
    _write_jsonl(paths.tutor_sealed, tutor_sealed)
    _write_json(paths.tutor_few_shot, tutor_few_shot)
    sealed_materials = sorted(_material_ids(tutor_sealed))
    seal = {
        "schema_version": "studyhub.agent.sft.controlled_v2.tutor_seal.v2",
        "contract_revision": "semantic_v2_2",
        "dataset_path": str(paths.tutor_sealed),
        "dataset_sha256": sha256_file(paths.tutor_sealed),
        "records": len(tutor_sealed),
        "family_counts": dict(
            sorted(Counter(str(row["task_family"]) for row in tutor_sealed).items())
        ),
        "material_ids": sealed_materials,
        "training_eligible": False,
        "evaluated": False,
        "single_use": True,
        "opened_for_model_selection": False,
    }
    _write_json(old_seal_path, seal)

    amended_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    amendment = {
        "amendment_id": AMENDMENT_ID,
        "at": amended_at,
        "timing": "before_any_selection_event",
        "reason": (
            "The no-answer query combined an answerable page explanation with an "
            "unanswerable request while the teacher target rejected the whole query. "
            "The corrected query is wholly unsupported by the visible evidence."
        ),
        "training_data_changed": False,
        "training_configs_changed": False,
        "gate_thresholds_changed": False,
        "previous_tutor_challenge_sha256": sha256_file(
            archive / paths.tutor_challenge.name
        ),
        "new_tutor_challenge_sha256": sha256_file(paths.tutor_challenge),
        "previous_tutor_sealed_sha256": old_seal["dataset_sha256"],
        "new_tutor_sealed_sha256": seal["dataset_sha256"],
        "superseded_artifacts": str(archive),
        "superseded_evaluations": str(evaluation_archive),
    }

    refreshed = contract_payload()
    registry["schema_version"] = CONTRACT_VERSION
    registry["contract_sha256"] = contract_sha256()
    registry.setdefault("data_contract_amendments", []).append(amendment)
    registry["status"] = "batch_00_refrozen_semantic_v2_2"
    _write_json(paths.experiment_registry, registry)

    for key in (
        "schema_version",
        "selection",
        "runtime",
        "router_gate",
        "tutor_gate",
        "initial_experiments",
        "reference_experiments",
        "selection_order",
    ):
        pre_registration[key] = refreshed[key]
    pre_registration["contract_sha256"] = contract_sha256()
    pre_registration["data"]["tutor_challenge"] = {
        "path": str(paths.tutor_challenge),
        "sha256": sha256_file(paths.tutor_challenge),
        "records": len(tutor_challenge),
        "family_counts": dict(
            sorted(Counter(str(row["task_family"]) for row in tutor_challenge).items())
        ),
        "material_ids": sorted(_material_ids(tutor_challenge)),
        "contract_revision": "semantic_v2_2",
    }
    pre_registration["data"]["few_shot"]["tutor_sha256"] = sha256_file(
        paths.tutor_few_shot
    )
    pre_registration["data"]["tutor_sealed"] = {
        "seal_path": str(old_seal_path),
        "seal_sha256": sha256_file(old_seal_path),
        "dataset_sha256": seal["dataset_sha256"],
        "records": seal["records"],
        "material_ids": seal["material_ids"],
        "evaluated": False,
        "contract_revision": "semantic_v2_2",
    }
    pre_registration.setdefault("data_contract_amendments", []).append(amendment)
    pre_registration["amended_at"] = amended_at
    pre_registration["audit"]["human_review"]["completed"] = False
    pre_registration["audit"]["human_review"]["high_risk_full_review_completed"] = False
    _write_json(paths.pre_registration, pre_registration)

    audit = audit_controlled_v2(paths=paths)
    context = build_context_study(paths=paths)
    result = {
        "schema_version": CONTRACT_VERSION,
        "amendment": amendment,
        "audit_passed": audit["passed"],
        "context_anchor_records": context["anchor_records"],
        "selection_events_before_amendment": 0,
    }
    _write_json(receipt_path, result)
    return result


def main() -> None:
    result = amend_tutor_contract()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
