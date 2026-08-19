from __future__ import annotations

import json

from studyhub_rag.config import ExperimentConfig
from studyhub_rag.schemas import QueryCase


def load_benchmark(config: ExperimentConfig, *, valid_material_ids: set[int] | None = None) -> list[QueryCase]:
    path = config.experiment_path(str(config.section("benchmark")["dataset_path"]))
    cases = [
        QueryCase.from_dict(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    ids = [case.query_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Benchmark query_id values must be unique")
    if valid_material_ids is not None:
        invalid = sorted(
            {material_id for case in cases for material_id in case.relevance if material_id not in valid_material_ids}
        )
        if invalid:
            raise ValueError(f"Benchmark references unavailable or non-free materials: {invalid}")
    return cases
