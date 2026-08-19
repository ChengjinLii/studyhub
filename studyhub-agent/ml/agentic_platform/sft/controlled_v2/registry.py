"""Append-only experiment registration and selection provenance."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .configs import generate_configs
from .contract import (
    ControlledPaths,
    ExperimentSpec,
    contract_payload,
    contract_sha256,
    reference_experiments,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def register_specs(
    specs: Iterable[ExperimentSpec],
    *,
    paths: ControlledPaths | None = None,
    reason: str,
    generate_training_configs: bool = True,
) -> dict[str, Any]:
    paths = paths or ControlledPaths()
    specs = tuple(specs)
    registry = json.loads(paths.experiment_registry.read_text(encoding="utf-8"))
    existing = {
        (str(item["experiment_id"]), int(item["seed"]))
        for section in (
            "initial_experiments",
            "reference_experiments",
            "dynamic_experiments",
        )
        for item in registry.get(section, [])
    }
    added: list[ExperimentSpec] = []
    for spec in specs:
        key = (spec.experiment_id, spec.seed)
        if key in existing:
            continue
        registry.setdefault("dynamic_experiments", []).append(spec.to_dict())
        existing.add(key)
        added.append(spec)
    if generate_training_configs:
        generate_configs(
            [spec for spec in specs if spec.reference_adapter_path is None], paths=paths
        )
    if added:
        registry.setdefault("registration_events", []).append(
            {
                "at": _now(),
                "reason": reason,
                "registered": [spec.to_dict() for spec in added],
            }
        )
        _write_json(paths.experiment_registry, registry)
    return registry


def record_selection(
    *,
    stage: str,
    candidates: Iterable[Mapping[str, Any]],
    selected: Iterable[ExperimentSpec],
    rule: str,
    paths: ControlledPaths | None = None,
) -> dict[str, Any]:
    paths = paths or ControlledPaths()
    registry = json.loads(paths.experiment_registry.read_text(encoding="utf-8"))
    event = {
        "stage": stage,
        "rule": rule,
        "candidates": [dict(item) for item in candidates],
        "selected": [item.to_dict() for item in selected],
        "sealed_data_read": False,
    }
    existing = [
        item
        for item in registry.get("selection_events", [])
        if item.get("stage") == stage
    ]
    if len(existing) > 1:
        raise RuntimeError(f"selection stage is recorded more than once: {stage}")
    if existing:
        comparable = {key: existing[0].get(key) for key in event}
        if comparable != event:
            raise RuntimeError(
                f"selection stage {stage} is already frozen with different evidence"
            )
        return existing[0]
    event["at"] = _now()
    registry.setdefault("selection_events", []).append(event)
    registry["status"] = f"selected_{stage}"
    _write_json(paths.experiment_registry, registry)
    return event


def apply_metadata_amendment(*, paths: ControlledPaths | None = None) -> dict[str, Any]:
    """Add reference bookkeeping without changing data, runtime, Gate, or arms."""

    paths = paths or ControlledPaths()
    registry = json.loads(paths.experiment_registry.read_text(encoding="utf-8"))
    registry["reference_experiments"] = [
        item.to_dict() for item in reference_experiments()
    ]
    registry["contract_sha256"] = contract_sha256()
    registry.setdefault("contract_amendments", []).append(
        {
            "at": _now(),
            "kind": "metadata_only",
            "change": (
                "Registered completed reference adapters and optional max_steps/"
                "reference path fields; frozen datasets, initial training configs, "
                "runtime, metrics, and Gate thresholds are unchanged."
            ),
        }
    )
    _write_json(paths.experiment_registry, registry)

    prereg = json.loads(paths.pre_registration.read_text(encoding="utf-8"))
    old_hash = str(prereg["contract_sha256"])
    refreshed = contract_payload()
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
        prereg[key] = refreshed[key]
    prereg["contract_sha256"] = contract_sha256()
    prereg.setdefault("contract_amendments", []).append(
        {
            "at": _now(),
            "kind": "metadata_only",
            "previous_contract_sha256": old_hash,
            "new_contract_sha256": contract_sha256(),
            "frozen_data_changed": False,
            "initial_training_config_changed": False,
            "gate_changed": False,
        }
    )
    _write_json(paths.pre_registration, prereg)
    return {"registry": registry, "pre_registration": prereg}
