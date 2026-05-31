from __future__ import annotations

import json
from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.moderation.rule_engine import ReviewAction, RuleBasedModerationEngine, load_material_samples


SAMPLE_PATH = AI_PLATFORM_ROOT / "data" / "sample_moderation_materials.json"


def test_moderation_engine_maps_samples_to_expected_actions() -> None:
    materials = load_material_samples(json.loads(SAMPLE_PATH.read_text(encoding="utf-8")))
    decisions = {decision.material_id: decision for decision in RuleBasedModerationEngine().review_many(materials)}

    assert decisions["material-safe-001"].action == ReviewAction.APPROVE
    assert decisions["material-review-001"].action == ReviewAction.MANUAL_REVIEW
    assert decisions["material-reject-001"].action == ReviewAction.REJECT
    assert decisions["material-hide-001"].action == ReviewAction.HIDE


def test_moderation_decision_exposes_risk_reasons() -> None:
    material = load_material_samples(json.loads(SAMPLE_PATH.read_text(encoding="utf-8")))[-1]
    decision = RuleBasedModerationEngine().review(material)

    assert decision.risk_score >= 100
    assert any("代写" in reason or "违规服务" in reason for reason in decision.risk_reasons)
    assert decision.to_dict()["matches"]
