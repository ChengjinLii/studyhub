from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.scripts.memory_summary_demo import run_memory_summary
from ai_platform.scripts.moderation_advisor_demo import run_moderation_advisor
from ai_platform.scripts.query_suggestion_demo import run_query_suggestion
from ai_platform.scripts.query_understanding_demo import run_query_understanding
from ai_platform.scripts.question_tutor_demo import run_question_tutor
from ai_platform.scripts.rollout_gate_demo import run_rollout_gate
from ai_platform.scripts.studycopilot_demo import run_studycopilot


DEFAULT_ROLLOUT_CONFIG = AI_PLATFORM_ROOT / "config" / "rollout_readiness.admin_shadow.json"


def run_v9_shadow_smoke(*, use_api: bool = False, rollout_config: Path = DEFAULT_ROLLOUT_CONFIG) -> dict[str, object]:
    study_query = "我两周后考通信原理，基础一般，想找速成资料和真题解析。"
    question = "这道链表题为什么我写错了？"
    studycopilot = run_studycopilot(study_query, use_api=use_api)
    recommended_ids = [item["id"] for item in studycopilot.get("recommendedItems", [])][:3]
    report: dict[str, object] = {
        "suite": "studycopilot-v9-admin-shadow-smoke",
        "mode": "api" if use_api else "mock",
        "productionIsolation": {
            "productionDatabaseWrites": False,
            "frontendEntryEnabled": False,
            "publicTrafficEnabled": False,
        },
        "queryUnderstanding": run_query_understanding(study_query, use_api=use_api),
        "querySuggestion": run_query_suggestion("通信原理", limit=5, use_api=use_api),
        "studyCopilot": studycopilot,
        "questionTutor": run_question_tutor(question, use_api=use_api),
        "moderationAdvisor": run_moderation_advisor(material_id="material-reject-001", use_api=use_api),
        "memorySummary": run_memory_summary(note="真题解析有帮助", recommended_item_ids=recommended_ids, use_api=use_api),
        "rolloutGate": run_rollout_gate(config_path=rollout_config),
    }
    report["passed"] = _validate_shadow_report(report)
    return report


def _validate_shadow_report(report: dict[str, object]) -> bool:
    isolation = report.get("productionIsolation")
    if not isinstance(isolation, dict) or any(isolation.values()):
        return False
    rollout_gate = report.get("rolloutGate")
    if not isinstance(rollout_gate, dict) or rollout_gate.get("allowed") is not True:
        return False
    studycopilot = report.get("studyCopilot")
    if not isinstance(studycopilot, dict):
        return False
    recommended = studycopilot.get("recommendedItems")
    reranked = studycopilot.get("rerankedCandidates")
    if not isinstance(recommended, list) or not recommended or not isinstance(reranked, list):
        return False
    reranked_ids = {str(item.get("id")) for item in reranked if isinstance(item, dict)}
    recommended_ids = {str(item.get("id")) for item in recommended if isinstance(item, dict)}
    if not recommended_ids or not recommended_ids <= reranked_ids:
        return False
    return all(
        isinstance(report.get(key), dict)
        for key in ("queryUnderstanding", "querySuggestion", "questionTutor", "moderationAdvisor", "memorySummary")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated StudyHub v9 admin/test shadow smoke suite.")
    parser.add_argument("--use-api", action="store_true", help="Use STUDYHUB_LLM_* env vars if configured.")
    parser.add_argument("--rollout-config", type=Path, default=DEFAULT_ROLLOUT_CONFIG)
    args = parser.parse_args()
    report = run_v9_shadow_smoke(use_api=args.use_api, rollout_config=args.rollout_config)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
