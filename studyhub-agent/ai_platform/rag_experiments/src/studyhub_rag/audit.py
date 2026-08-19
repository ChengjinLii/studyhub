from __future__ import annotations

import csv
import json
from typing import Any

from PIL import Image

from studyhub_rag.config import ExperimentConfig
from studyhub_rag.corpus import load_materials, read_corpus
from studyhub_rag.guards import require_experiment_output, verify_source_isolation

REQUIRED_METHODS = {
    "tfidf_char_2_4",
    "bm25_mixed_tokens",
    "bge_m3_exact",
    "bge_m3_hnsw",
    "bge_m3_ivf",
    "qwen3_embedding_06b_exact",
    "bm25_bge_weighted_06_04",
    "tfidf_bge_weighted_06_04",
    "bm25_bge_rrf",
    "tfidf_bge_rrf",
    "bm25_bge_rrf_bge_reranker",
}
REQUIRED_FIGURES = {
    "retrieval_quality.png",
    "quality_latency_tradeoff.png",
    "query_type_ndcg_heatmap.png",
}


def verify_results(config: ExperimentConfig) -> dict[str, Any]:
    errors = verify_source_isolation()
    report_root = require_experiment_output(config.experiment_path(str(config.section("outputs")["report_root"])))
    artifact_root = require_experiment_output(config.experiment_path(str(config.section("outputs")["artifact_root"])))
    summary_path = report_root / "summary.json"
    if not summary_path.exists():
        errors.append(f"Missing {summary_path}")
        return {"ok": False, "errors": errors}

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest = summary.get("manifest") or {}
    metrics = summary.get("metrics") or {}
    if manifest.get("database_access") != "forbidden":
        errors.append("Experiment manifest does not prohibit database access")
    if manifest.get("source_mode") != "static_backup_read_only":
        errors.append("Experiment manifest is not marked as static read-only")
    missing_methods = sorted(REQUIRED_METHODS - set(metrics))
    if missing_methods:
        errors.append(f"Missing benchmark methods: {missing_methods}")
    leaking_methods = {
        method: values.get("permission_leaked_ids")
        for method, values in metrics.items()
        if int(values.get("permission_leak_count") or 0) != 0
    }
    if leaking_methods:
        errors.append(f"Permission leakage detected: {leaking_methods}")

    free_ids = {int(material["id"]) for material in load_materials(config)}
    chunks = read_corpus(config)
    corpus_ids = {chunk.material_id for chunk in chunks}
    if not corpus_ids.issubset(free_ids):
        errors.append(f"Corpus contains non-free material IDs: {sorted(corpus_ids - free_ids)}")

    ocr_manifest_path = artifact_root / "ocr" / "manifest.json"
    if not ocr_manifest_path.exists():
        errors.append("OCR manifest is missing")
        ocr_manifest: dict[str, Any] = {}
    else:
        ocr_manifest = json.loads(ocr_manifest_path.read_text(encoding="utf-8"))
        if ocr_manifest.get("input_images") != ocr_manifest.get("records"):
            errors.append("OCR record count does not match input image count")
        if ocr_manifest.get("failures"):
            errors.append(f"OCR failures remain: {ocr_manifest['failures']}")

    metrics_path = report_root / "metrics.csv"
    with metrics_path.open(encoding="utf-8-sig") as handle:
        metric_rows = list(csv.DictReader(handle))
    if {row["method"] for row in metric_rows} != set(metrics):
        errors.append("metrics.csv methods do not match summary.json")

    figures = report_root / "figures"
    for filename in REQUIRED_FIGURES:
        path = figures / filename
        if not path.exists() or path.stat().st_size == 0:
            errors.append(f"Missing or empty figure: {path}")
            continue
        try:
            with Image.open(path) as image:
                image.verify()
        except Exception as error:
            errors.append(f"Invalid figure {path}: {type(error).__name__}: {error}")

    report_path = report_root / "RAG_EXPERIMENT_REPORT.md"
    if not report_path.exists() or not report_path.read_text(encoding="utf-8").startswith("# StudyHub RAG"):
        errors.append("RAG experiment report is missing or malformed")

    return {
        "ok": not errors,
        "errors": errors,
        "methods": len(metrics),
        "materials": len(corpus_ids),
        "chunks": len(chunks),
        "ocr_records": ocr_manifest.get("records", 0),
        "figures": len(REQUIRED_FIGURES),
        "permission_leaks": sum(int(values.get("permission_leak_count") or 0) for values in metrics.values()),
        "database_access": manifest.get("database_access"),
        "source_mode": manifest.get("source_mode"),
    }
