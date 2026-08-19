from __future__ import annotations

from studyhub_rag.benchmark import load_benchmark
from studyhub_rag.config import load_config
from studyhub_rag.corpus import load_materials


def test_benchmark_only_references_free_snapshot_materials() -> None:
    config = load_config("configs/benchmark.yaml")
    materials = load_materials(config)
    free_ids = {int(material["id"]) for material in materials}
    cases = load_benchmark(config, valid_material_ids=free_ids)
    assert len(cases) == 60
    assert sum(case.answerable for case in cases) == 55
    assert sum(not case.answerable for case in cases) == 5
