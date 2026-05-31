from __future__ import annotations

import json
from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.rollout.gate import RolloutGate, RolloutReadinessConfig
from ai_platform.scripts.rollout_gate_demo import run_rollout_gate
from ai_platform.scripts.studycopilot_eval import run_eval


def _ready_config() -> RolloutReadinessConfig:
    return RolloutReadinessConfig(
        feature_flag_defined=True,
        rollback_plan_defined=True,
        cost_monitoring_defined=True,
        privacy_policy_defined=True,
        human_fallback_defined=True,
        production_database_writes_disabled=True,
        frontend_entry_disabled=True,
        admin_or_test_only=True,
    )


def test_rollout_gate_allows_admin_shadow_when_all_checks_pass() -> None:
    report = RolloutGate().evaluate(run_eval(), _ready_config())

    assert report["allowed"] is True
    assert report["mode"] == "admin_test_shadow"
    assert all(check["passed"] for check in report["checks"])


def test_rollout_gate_blocks_when_readiness_config_is_incomplete() -> None:
    report = RolloutGate().evaluate(run_eval(), RolloutReadinessConfig())

    assert report["allowed"] is False
    failed = {check["name"] for check in report["checks"] if not check["passed"]}
    assert "feature_flag_defined" in failed
    assert "rollback_plan_defined" in failed
    assert "cost_monitoring_defined" in failed


def test_rollout_gate_demo_uses_config_file(tmp_path: Path) -> None:
    config_path = tmp_path / "rollout.json"
    config_path.write_text(json.dumps(_ready_config().to_dict()), encoding="utf-8")

    report = run_rollout_gate(config_path=config_path)

    assert report["allowed"] is True


def test_admin_shadow_config_is_machine_readable_and_allowed() -> None:
    config_path = AI_PLATFORM_ROOT / "config" / "rollout_readiness.admin_shadow.json"

    report = run_rollout_gate(config_path=config_path)

    assert report["allowed"] is True
    assert report["mode"] == "admin_test_shadow"
    assert report["config"]["productionDatabaseWritesDisabled"] is True
    assert report["config"]["frontendEntryDisabled"] is True
    assert report["config"]["adminOrTestOnly"] is True


def test_rollout_gate_blocks_failed_eval_even_when_config_ready() -> None:
    report = RolloutGate().evaluate({"passed": False, "passedCount": 4, "caseCount": 5}, _ready_config())

    assert report["allowed"] is False
    failed = {check["name"] for check in report["checks"] if not check["passed"]}
    assert failed == {"offline_eval_passed"}
