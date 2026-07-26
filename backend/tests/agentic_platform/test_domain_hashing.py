from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st
from pydantic import ValidationError

from app.agentic_platform.domain.artifact import ArtifactRef
from app.agentic_platform.domain.decision import AgentDecision
from app.agentic_platform.domain.hashing import canonical_hash, canonical_json, json_schema_hash
from app.agentic_platform.domain.plan import AgentPlan, PlanStep
from app.agentic_platform.domain.state import AgentTaskState, StateDelta, WorkingSet
from app.agentic_platform.domain.transition import AgentTransitionEvent
from tests.agentic_platform.factories import transition


def _step(step_id: str, depends_on: list[str]) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        title=f"Step {step_id}",
        depends_on=depends_on,
        capability="test.capability",
        completion_check="complete",
    )


def test_canonical_json_has_a_fixed_golden_hash_and_is_order_stable() -> None:
    payload = {"z": 2, "a": "学习", "nested": [True, None]}

    assert canonical_json(payload) == '{"a":"学习","nested":[true,null],"z":2}'
    assert canonical_hash(payload) == "5a1ebd306792503677fc16f53a0e215e50d6c77dd50206222726793b906c02f2"
    assert canonical_hash({"nested": [True, None], "z": 2, "a": "学习"}) == canonical_hash(payload)


def test_canonical_hash_ignores_export_time_but_detects_business_changes() -> None:
    first = transition(exported_at=datetime(2026, 7, 26, tzinfo=UTC))
    later_export = first.model_copy(update={"exported_at": datetime(2026, 7, 27, tzinfo=UTC)})
    changed_turn = first.model_copy(update={"turn_index": 1})

    assert first.canonical_hash() == later_export.canonical_hash()
    assert first.canonical_hash() != changed_turn.canonical_hash()


def test_domain_json_schemas_are_exportable_and_have_stable_golden_fingerprints() -> None:
    schemas = {
        "AgentTaskState": AgentTaskState.model_json_schema(),
        "AgentDecision": AgentDecision.model_json_schema(),
        "StateDelta": StateDelta.model_json_schema(),
        "AgentTransitionEvent": AgentTransitionEvent.model_json_schema(),
        "ArtifactRef": ArtifactRef.model_json_schema(),
    }

    golden_manifest_path = (
        Path(__file__).resolve().parents[3]
        / "reports"
        / "recagent"
        / "agentic-platform"
        / "contracts"
        / "agentic-domain-schema-golden-v1.json"
    )
    golden_manifest = json.loads(golden_manifest_path.read_text(encoding="utf-8"))

    assert all(schema["additionalProperties"] is False for schema in schemas.values())
    assert golden_manifest["schemas"] == {
        "ArtifactRef": json_schema_hash(ArtifactRef),
        "AgentDecision": json_schema_hash(AgentDecision),
        "StateDelta": json_schema_hash(StateDelta),
        "AgentTaskState": json_schema_hash(AgentTaskState),
        "AgentTransitionEvent": json_schema_hash(AgentTransitionEvent),
    }


@st.composite
def acyclic_steps(draw: st.DrawFn) -> list[tuple[str, list[str]]]:
    step_ids = draw(
        st.lists(
            st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=8),
            min_size=1,
            max_size=10,
            unique=True,
        )
    )
    result: list[tuple[str, list[str]]] = []
    for index, step_id in enumerate(step_ids):
        dependencies = []
        if index:
            dependencies = draw(st.lists(st.sampled_from(step_ids[:index]), unique=True, max_size=index))
        result.append((step_id, dependencies))
    return result


@settings(max_examples=50, deadline=None)
@given(acyclic_steps())
def test_property_generated_forward_dependency_plans_are_valid_dags(steps: list[tuple[str, list[str]]]) -> None:
    plan = AgentPlan(
        plan_id="property-plan",
        version=1,
        objective="Validate generated DAG",
        created_by_policy_version="property-test",
        steps=[_step(step_id, depends_on) for step_id, depends_on in steps],
    )

    assert [step.step_id for step in plan.steps] == [step_id for step_id, _ in steps]


@settings(max_examples=30, deadline=None)
@given(st.lists(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=8), min_size=1, max_size=10, unique=True))
def test_property_generated_ids_remain_disjoint_and_conflicts_are_rejected(ids: list[str]) -> None:
    working_set = WorkingSet(accepted_ids=ids[::2], rejected_ids=ids[1::2])

    assert set(working_set.accepted_ids).isdisjoint(working_set.rejected_ids)
    with pytest.raises(ValidationError, match="conflict"):
        WorkingSet(accepted_ids=[ids[0]], rejected_ids=[ids[0]])
