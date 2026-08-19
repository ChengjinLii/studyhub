"""Validate existing StudyHub Agent SFT specification JSONL artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .build_validation_dataset import (
    DEFAULT_CHUNKS_PATH,
    DEFAULT_MATERIALS_PATH,
    DEFAULT_OUTPUT_DIR,
    EXPECTED_PROFILE_COUNTS,
    EXPECTED_SPLIT_COUNTS,
)
from .spec import audit_datasets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--router",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "router_tool_2b.jsonl",
    )
    parser.add_argument(
        "--tutor",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "grounded_tutor_9b.jsonl",
    )
    parser.add_argument("--materials", type=Path, default=DEFAULT_MATERIALS_PATH)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS_PATH)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    audit = audit_datasets(
        [args.router, args.tutor],
        materials_path=args.materials,
        chunks_path=args.chunks,
        expected_profile_counts=EXPECTED_PROFILE_COUNTS,
        expected_split_counts=EXPECTED_SPLIT_COUNTS,
    )
    result = audit.to_dict()
    serialized = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    if not audit.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
