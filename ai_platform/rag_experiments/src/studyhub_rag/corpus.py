from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from studyhub_rag.config import ExperimentConfig
from studyhub_rag.guards import require_experiment_output, require_static_snapshot
from studyhub_rag.schemas import Chunk
from studyhub_rag.text import normalize_text, split_text


def _clean(value: Any) -> str:
    return normalize_text(str(value or ""))


def load_materials(config: ExperimentConfig) -> list[dict[str, Any]]:
    data = config.section("data")
    snapshot_root = config.repo_path(str(data["snapshot_root"]))
    materials_path = require_static_snapshot(snapshot_root / str(data["materials_file"]), snapshot_root)
    payload = json.loads(materials_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("materials.json must contain a list")
    if bool(data.get("free_only", True)):
        payload = [item for item in payload if item.get("free") is True and float(item.get("price") or 0) <= 0]
    return payload


def _metadata_text(material: dict[str, Any]) -> str:
    fields = [
        f"资料标题：{_clean(material.get('title'))}",
        f"资料简介：{_clean(material.get('description'))}",
        f"标签：{'、'.join(str(tag) for tag in material.get('tags') or [])}",
        f"学校：{_clean(material.get('school'))}",
        f"学院：{_clean(material.get('college'))}",
        f"专业：{_clean(material.get('major'))}",
        f"课程类型：{_clean(material.get('courseCategory'))}",
        f"年级：{_clean(material.get('gradeValue'))}",
    ]
    return "\n".join(field for field in fields if not field.endswith("："))


def _base_chunk(material: dict[str, Any], *, chunk_id: str, text: str, **extra: Any) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        material_id=int(material["id"]),
        title=_clean(material.get("title")),
        text=text,
        tags=tuple(str(tag) for tag in material.get("tags") or []),
        course_category=_clean(material.get("courseCategory")),
        school=_clean(material.get("school")),
        college=_clean(material.get("college")),
        major=_clean(material.get("major")),
        grade_type=_clean(material.get("gradeType")),
        grade_value=_clean(material.get("gradeValue")),
        **extra,
    )


def load_ocr_records(config: ExperimentConfig) -> list[dict[str, Any]]:
    artifact_root = config.experiment_path(str(config.section("outputs")["artifact_root"]))
    path = require_experiment_output(artifact_root / "ocr" / "preview_text.jsonl")
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def build_chunks(config: ExperimentConfig) -> list[Chunk]:
    data = config.section("data")
    materials = load_materials(config)
    by_id = {int(item["id"]): item for item in materials}
    chunks: list[Chunk] = []
    if bool(data.get("include_metadata", True)):
        for material in materials:
            material_id = int(material["id"])
            chunks.append(_base_chunk(material, chunk_id=f"{material_id}:metadata:0", text=_metadata_text(material)))
    if bool(data.get("include_ocr", True)):
        max_chars = int(data.get("chunk_size_chars", 700))
        overlap = int(data.get("chunk_overlap_chars", 100))
        for record in load_ocr_records(config):
            material_id = int(record["material_id"])
            material = by_id.get(material_id)
            if material is None:
                continue
            page = int(record["page"])
            page_chunks = split_text(
                str(record.get("text") or ""),
                max_chars=max_chars,
                overlap_chars=overlap,
            )
            for index, text in enumerate(page_chunks):
                chunks.append(
                    _base_chunk(
                        material,
                        chunk_id=f"{material_id}:preview:{page}:{index}",
                        text=text,
                        page=page,
                        source_kind="preview_ocr",
                        source_path=str(record.get("source_path") or ""),
                    )
                )
    if any(chunk.material_id not in by_id for chunk in chunks):
        raise AssertionError("Corpus contains a material outside the free snapshot")
    return chunks


def corpus_fingerprint(chunks: Iterable[Chunk]) -> str:
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(json.dumps(chunk.to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()[:16]


def write_corpus(config: ExperimentConfig, chunks: list[Chunk]) -> Path:
    artifact_root = config.experiment_path(str(config.section("outputs")["artifact_root"]))
    output = require_experiment_output(artifact_root / "corpus" / "chunks.jsonl")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")
    return output


def read_corpus(config: ExperimentConfig) -> list[Chunk]:
    artifact_root = config.experiment_path(str(config.section("outputs")["artifact_root"]))
    path = require_experiment_output(artifact_root / "corpus" / "chunks.jsonl")
    if not path.exists():
        raise FileNotFoundError(f"Corpus does not exist; run build-corpus first: {path}")
    return [Chunk.from_dict(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
