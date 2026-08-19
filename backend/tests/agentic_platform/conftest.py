from __future__ import annotations

from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PRIVATE_SFT_CORPUS_FILES = (
    PROJECT_ROOT / "backup/oss_materials/metadata/materials.jsonl",
    PROJECT_ROOT / "studyhub-agent/ai_platform/rag_experiments/artifacts/corpus/chunks.jsonl",
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    missing = [path for path in PRIVATE_SFT_CORPUS_FILES if not path.is_file()]
    if not missing:
        return
    reason = "requires ignored frozen SFT corpus: " + ", ".join(str(path.relative_to(PROJECT_ROOT)) for path in missing)
    marker = pytest.mark.skip(reason=reason)
    for item in items:
        if item.get_closest_marker("private_sft_corpus") is not None:
            item.add_marker(marker)
