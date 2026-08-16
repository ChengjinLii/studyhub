from __future__ import annotations

import argparse
import json

from studyhub_rag.audit import verify_results
from studyhub_rag.config import EXPERIMENT_ROOT, load_config
from studyhub_rag.corpus import build_chunks, corpus_fingerprint, write_corpus
from studyhub_rag.experiment import run_experiment
from studyhub_rag.guards import require_static_snapshot, verify_source_isolation
from studyhub_rag.ocr import ocr_previews

DEFAULT_CONFIG = EXPERIMENT_ROOT / "configs" / "benchmark.yaml"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="studyhub-rag", description="Read-only StudyHub RAG experiments")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Experiment YAML configuration")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("verify-isolation", help="Reject production/backend/database coupling")
    subparsers.add_parser("verify-results", help="Audit corpus boundaries and all generated RAG results")
    ocr = subparsers.add_parser("ocr-previews", help="OCR free-material preview pages from the static backup")
    ocr.add_argument("--limit", type=int, default=None, help="Optional page limit for a smoke run")
    subparsers.add_parser("build-corpus", help="Build free-only metadata and OCR chunks")
    run = subparsers.add_parser("run", help="Run retrieval comparisons and generate reports")
    run.add_argument("--mode", choices=("sparse", "all"), default="all")
    return parser


def main() -> None:
    args = _parser().parse_args()
    config = load_config(args.config)
    if args.command == "verify-isolation":
        violations = verify_source_isolation()
        data = config.section("data")
        snapshot_root = config.repo_path(str(data["snapshot_root"]))
        materials = require_static_snapshot(snapshot_root / str(data["materials_file"]), snapshot_root)
        result = {
            "ok": not violations,
            "violations": violations,
            "input": str(materials),
            "source_mode": "static_backup_read_only",
            "database_access": "forbidden",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if violations:
            raise SystemExit(1)
    elif args.command == "verify-results":
        result = verify_results(config)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["ok"]:
            raise SystemExit(1)
    elif args.command == "ocr-previews":
        print(json.dumps(ocr_previews(config, limit=args.limit), ensure_ascii=False, indent=2))
    elif args.command == "build-corpus":
        chunks = build_chunks(config)
        path = write_corpus(config, chunks)
        result = {
            "path": str(path),
            "chunks": len(chunks),
            "materials": len({chunk.material_id for chunk in chunks}),
            "metadata_chunks": sum(chunk.source_kind == "metadata" for chunk in chunks),
            "ocr_chunks": sum(chunk.source_kind == "preview_ocr" for chunk in chunks),
            "fingerprint": corpus_fingerprint(chunks),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "run":
        print(json.dumps(run_experiment(config, mode=args.mode)["manifest"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
