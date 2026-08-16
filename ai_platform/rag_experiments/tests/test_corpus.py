from __future__ import annotations

import json
from pathlib import Path

from studyhub_rag.config import ExperimentConfig
from studyhub_rag.corpus import build_chunks
from studyhub_rag.text import split_text


def _config(snapshot: Path) -> ExperimentConfig:
    return ExperimentConfig(
        raw={
            "data": {
                "snapshot_root": str(snapshot),
                "materials_file": "metadata/materials.json",
                "free_only": True,
                "include_metadata": True,
                "include_ocr": False,
            },
            "outputs": {"artifact_root": "artifacts"},
        },
        path=snapshot / "config.yaml",
    )


def test_corpus_excludes_paid_materials(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    metadata = snapshot / "metadata"
    metadata.mkdir(parents=True)
    materials = [
        {"id": 1, "title": "免费高数笔记", "free": True, "price": 0, "tags": ["高数"]},
        {"id": 2, "title": "付费隐藏资料", "free": False, "price": 9.9, "tags": ["隐藏"]},
    ]
    (metadata / "materials.json").write_text(json.dumps(materials, ensure_ascii=False), encoding="utf-8")
    chunks = build_chunks(_config(snapshot))
    assert [chunk.material_id for chunk in chunks] == [1]
    assert "免费高数笔记" in chunks[0].retrieval_text


def test_split_text_has_bounded_overlap() -> None:
    text = "第一段内容。" * 100
    chunks = split_text(text, max_chars=80, overlap_chars=10)
    assert len(chunks) > 1
    assert all(0 < len(chunk) <= 80 for chunk in chunks)
