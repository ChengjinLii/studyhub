from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.moderation.llm_advisor import LLMModerationAdvisor, MockModerationAdvisor
from ai_platform.moderation.rule_engine import RuleBasedModerationEngine, load_material_samples
from ai_platform.scripts.moderation_demo import DEFAULT_SAMPLE_PATH
from ai_platform.serving.llm_provider import get_env_chat_provider


def run_moderation_advisor(*, sample_path: Path = DEFAULT_SAMPLE_PATH, material_id: str | None = None, use_api: bool = False) -> dict[str, object]:
    raw_items = json.loads(sample_path.read_text(encoding="utf-8"))
    materials = load_material_samples(raw_items)
    if material_id:
        materials = [material for material in materials if material.id == material_id]
    engine = RuleBasedModerationEngine()
    provider = get_env_chat_provider() if use_api else None
    advisor = LLMModerationAdvisor(provider) if provider else MockModerationAdvisor()
    items = []
    for material in materials:
        decision = engine.review(material)
        items.append({"decision": decision.to_dict(), "advice": advisor.advise(material, decision).to_dict()})
    return {"items": items}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated StudyHub LLM moderation advisor demo.")
    parser.add_argument("--sample-path", type=Path, default=DEFAULT_SAMPLE_PATH)
    parser.add_argument("--material-id")
    parser.add_argument("--use-api", action="store_true", help="Use STUDYHUB_LLM_* env vars if configured.")
    args = parser.parse_args()
    print(
        json.dumps(
            run_moderation_advisor(sample_path=args.sample_path, material_id=args.material_id, use_api=args.use_api),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
