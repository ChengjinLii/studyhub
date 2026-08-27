#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from studyhub_agent.benchmark_v2.builder import DEFAULT_SEED, build_benchmark


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus",
        type=Path,
        default=project / "ai_platform/rag_experiments/artifacts/corpus/chunks.jsonl",
    )
    parser.add_argument(
        "--materials",
        type=Path,
        default=project.parent / "backup/oss_materials/metadata/materials.json",
    )
    parser.add_argument("--public-root", type=Path, default=project / "benchmarks/studyhub-agent-v2")
    parser.add_argument("--hidden-root", type=Path, default=project / "artifacts/benchmark-v2/studyhub-agent-v2")
    parser.add_argument(
        "--web-snapshot",
        type=Path,
        default=project / "artifacts/benchmark-v2/web-snapshots/snapshot.jsonl",
    )
    parser.add_argument(
        "--web-source-config",
        type=Path,
        default=project / "configs/benchmark-v2-web-sources.json",
    )
    parser.add_argument(
        "--web-lock",
        type=Path,
        default=project / "configs/benchmark-v2-web-lock.json",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build_benchmark(
        corpus_path=args.corpus.resolve(),
        materials_path=args.materials.resolve(),
        public_root=args.public_root.resolve(),
        hidden_root=args.hidden_root.resolve(),
        web_snapshot_path=args.web_snapshot.resolve(),
        web_source_config_path=args.web_source_config.resolve(),
        web_lock_path=args.web_lock.resolve(),
        seed=args.seed,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
