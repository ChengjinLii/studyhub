from __future__ import annotations

import fcntl
import json
from contextlib import contextmanager
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

from studyhub_rag.config import ExperimentConfig
from studyhub_rag.corpus import load_materials
from studyhub_rag.guards import require_experiment_output, require_static_snapshot
from studyhub_rag.text import normalize_text


def _extract_lines(result: Any) -> tuple[list[str], list[float]]:
    payload = result[0] if isinstance(result, tuple) else result
    if hasattr(payload, "txts"):
        texts = [str(value) for value in payload.txts]
        scores = [float(value) for value in getattr(payload, "scores", [])]
        return texts, scores
    texts: list[str] = []
    scores: list[float] = []
    for item in payload or []:
        if isinstance(item, dict):
            text = item.get("text") or item.get("txt") or ""
            score = item.get("score") or item.get("confidence") or 0.0
        elif isinstance(item, (list, tuple)) and len(item) >= 3:
            text, score = item[1], item[2]
        else:
            continue
        if str(text).strip():
            texts.append(str(text))
            scores.append(float(score))
    return texts, scores


def _write_records(path: Path, records: dict[tuple[int, int], dict[str, Any]]) -> None:
    temporary = path.with_suffix(".jsonl.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for key in sorted(records):
            handle.write(json.dumps(records[key], ensure_ascii=False) + "\n")
    temporary.replace(path)


@contextmanager
def _exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(f"Another OCR process already holds {path}") from error
        yield


def ocr_previews(config: ExperimentConfig, *, limit: int | None = None) -> dict[str, Any]:
    artifact_root = config.experiment_path(str(config.section("outputs")["artifact_root"]))
    lock_path = require_experiment_output(artifact_root / "ocr" / ".ocr.lock")
    with _exclusive_lock(lock_path):
        return _ocr_previews_unlocked(config, limit=limit)


def _ocr_previews_unlocked(config: ExperimentConfig, *, limit: int | None = None) -> dict[str, Any]:
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as error:
        raise RuntimeError("OCR dependencies are missing; run `uv sync --extra ocr`") from error
    data = config.section("data")
    snapshot_root = config.repo_path(str(data["snapshot_root"]))
    preview_root = require_static_snapshot(snapshot_root / str(data["preview_root"]), snapshot_root)
    free_ids = {int(material["id"]) for material in load_materials(config)}
    images = sorted(
        path
        for path in preview_root.glob("*/preview/*")
        if path.suffix.lower() in {".jpg", ".jpeg", ".png"}
        and path.parent.parent.name.isdigit()
        and int(path.parent.parent.name) in free_ids
    )
    if limit is not None:
        images = images[: max(0, limit)]
    artifact_root = config.experiment_path(str(config.section("outputs")["artifact_root"]))
    output = require_experiment_output(artifact_root / "ocr" / "preview_text.jsonl")
    manifest_path = require_experiment_output(artifact_root / "ocr" / "manifest.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[tuple[int, int], dict[str, Any]] = {}
    if output.exists():
        for line in output.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                existing[(int(record["material_id"]), int(record["page"]))] = record
    engine = RapidOCR()
    processed = 0
    failures: list[dict[str, str]] = []
    started = perf_counter()
    for image in images:
        material_id = int(image.parent.parent.name)
        page_text = image.stem.lower().lstrip("p")
        page = int(page_text) if page_text.isdigit() else len(existing) + 1
        key = (material_id, page)
        if key in existing:
            continue
        try:
            result = engine(str(image))
            texts, scores = _extract_lines(result)
            existing[key] = {
                "material_id": material_id,
                "page": page,
                "text": normalize_text("\n".join(texts)),
                "line_count": len(texts),
                "mean_confidence": mean(scores) if scores else 0.0,
                "source_path": str(image.relative_to(snapshot_root)),
            }
            processed += 1
            if processed % 10 == 0:
                _write_records(output, existing)
                print(f"[ocr] completed={len(existing)}/{len(images)} failures={len(failures)}", flush=True)
        except Exception as error:  # OCR should continue and report corrupt pages.
            failures.append({"path": str(image), "error": f"{type(error).__name__}: {error}"})
    _write_records(output, existing)
    manifest = {
        "schema": "studyhub-preview-ocr-v1",
        "input_images": len(images),
        "records": len(existing),
        "processed_this_run": processed,
        "failures": failures,
        "elapsed_seconds": perf_counter() - started,
        "database_access": "forbidden",
        "source_mode": "static_backup_read_only",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
