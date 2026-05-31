from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.serving.embedding_provider import EmbeddingRequest, get_mock_embedding_provider


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated mock embedding provider demo.")
    parser.add_argument("texts", nargs="*", default=["通信原理期末复习", "数据结构实验报告"])
    parser.add_argument("--dimensions", type=int, default=32)
    args = parser.parse_args()

    provider = get_mock_embedding_provider(dimensions=args.dimensions)
    response = provider.embed(EmbeddingRequest(texts=args.texts))
    print(
        json.dumps(
            {
                "provider": response.provider,
                "dimensions": response.dimensions,
                "vectorCount": len(response.vectors),
                "preview": [vector[:6] for vector in response.vectors],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
