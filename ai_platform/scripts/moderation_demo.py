from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.moderation.rule_engine import RuleBasedModerationEngine, load_material_samples


DEFAULT_SAMPLE_PATH = AI_PLATFORM_ROOT / "data" / "sample_moderation_materials.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated rule-based moderation over sample StudyHub materials.")
    parser.add_argument("--sample-path", type=Path, default=DEFAULT_SAMPLE_PATH)
    parser.add_argument("--material-id", help="Optional sample material id to review.")
    args = parser.parse_args()

    raw_items = json.loads(args.sample_path.read_text(encoding="utf-8"))
    materials = load_material_samples(raw_items)
    if args.material_id:
        materials = [material for material in materials if material.id == args.material_id]
    engine = RuleBasedModerationEngine()
    decisions = [decision.to_dict() for decision in engine.review_many(materials)]
    print(json.dumps({"decisions": decisions}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
