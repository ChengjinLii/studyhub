from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.rollout.gate import RolloutGate, RolloutReadinessConfig
from ai_platform.scripts.studycopilot_eval import run_eval


DEFAULT_CONFIG_PATH = AI_PLATFORM_ROOT / "config" / "rollout_readiness.example.json"


def run_rollout_gate(*, config_path: Path = DEFAULT_CONFIG_PATH) -> dict[str, object]:
    config = RolloutReadinessConfig.from_dict(json.loads(config_path.read_text(encoding="utf-8")))
    return RolloutGate().evaluate(run_eval(), config)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate StudyCopilot v9 production-entry rollout gate.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args()
    report = run_rollout_gate(config_path=args.config)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["allowed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
