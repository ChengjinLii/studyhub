from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.preprocessing.ai_document import build_ai_documents, load_source_records


DEFAULT_SAMPLE_PATH = AI_PLATFORM_ROOT / "data" / "sample_documents.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert isolated StudyHub sample records into unified AI documents.")
    parser.add_argument("--sample-path", type=Path, default=DEFAULT_SAMPLE_PATH)
    parser.add_argument("--chunk-size", type=int, default=160)
    parser.add_argument("--overlap", type=int, default=24)
    args = parser.parse_args()

    raw_items = json.loads(args.sample_path.read_text(encoding="utf-8"))
    documents = build_ai_documents(load_source_records(raw_items), chunk_size=args.chunk_size, overlap=args.overlap)
    print(json.dumps({"documents": [document.to_dict() for document in documents]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
