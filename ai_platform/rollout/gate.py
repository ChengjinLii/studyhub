from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RolloutReadinessConfig:
    feature_flag_defined: bool = False
    rollback_plan_defined: bool = False
    cost_monitoring_defined: bool = False
    privacy_policy_defined: bool = False
    human_fallback_defined: bool = False
    production_database_writes_disabled: bool = True
    frontend_entry_disabled: bool = True
    admin_or_test_only: bool = True

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RolloutReadinessConfig":
        return cls(
            feature_flag_defined=bool(value.get("featureFlagDefined")),
            rollback_plan_defined=bool(value.get("rollbackPlanDefined")),
            cost_monitoring_defined=bool(value.get("costMonitoringDefined")),
            privacy_policy_defined=bool(value.get("privacyPolicyDefined")),
            human_fallback_defined=bool(value.get("humanFallbackDefined")),
            production_database_writes_disabled=bool(value.get("productionDatabaseWritesDisabled", True)),
            frontend_entry_disabled=bool(value.get("frontendEntryDisabled", True)),
            admin_or_test_only=bool(value.get("adminOrTestOnly", True)),
        )

    def to_dict(self) -> dict[str, bool]:
        return {
            "featureFlagDefined": self.feature_flag_defined,
            "rollbackPlanDefined": self.rollback_plan_defined,
            "costMonitoringDefined": self.cost_monitoring_defined,
            "privacyPolicyDefined": self.privacy_policy_defined,
            "humanFallbackDefined": self.human_fallback_defined,
            "productionDatabaseWritesDisabled": self.production_database_writes_disabled,
            "frontendEntryDisabled": self.frontend_entry_disabled,
            "adminOrTestOnly": self.admin_or_test_only,
        }


class RolloutGate:
    """Production-entry gate for the isolated v9 StudyCopilot prototype."""

    def evaluate(self, eval_report: dict[str, Any], config: RolloutReadinessConfig) -> dict[str, Any]:
        checks = [
            _check("offline_eval_passed", bool(eval_report.get("passed")), f"{eval_report.get('passedCount', 0)}/{eval_report.get('caseCount', 0)} cases"),
            _check("feature_flag_defined", config.feature_flag_defined, "semantic/agent rollout must be switchable"),
            _check("rollback_plan_defined", config.rollback_plan_defined, "must define disable path and fallback to ordinary search"),
            _check("cost_monitoring_defined", config.cost_monitoring_defined, "must track model calls and token budget"),
            _check("privacy_policy_defined", config.privacy_policy_defined, "must define data minimization, retention, and deletion"),
            _check("human_fallback_defined", config.human_fallback_defined, "must route uncertain AI output to normal search or human review"),
            _check("production_database_writes_disabled", config.production_database_writes_disabled, "prototype must not write production DB"),
            _check("frontend_entry_disabled", config.frontend_entry_disabled, "prototype must not expose public frontend entry"),
            _check("admin_or_test_only", config.admin_or_test_only, "any smoke rollout must be admin/test only"),
        ]
        allowed = all(check["passed"] for check in checks)
        return {
            "gate": "studycopilot-v9-rollout",
            "allowed": allowed,
            "mode": "admin_test_shadow" if allowed else "blocked",
            "checks": checks,
            "config": config.to_dict(),
        }


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": passed, "detail": detail}
