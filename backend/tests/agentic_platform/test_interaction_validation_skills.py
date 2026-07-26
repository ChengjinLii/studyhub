from __future__ import annotations

import asyncio

from app.agentic_platform.skills.context import SkillExecutionContext, SkillExecutionMode
from app.agentic_platform.skills.executor import LiveSkillExecutor
from app.agentic_platform.skills.registry import build_default_skill_registry


def _context(*, idempotency_key: str | None = None) -> SkillExecutionContext:
    return SkillExecutionContext(
        admin_actor_id=3,
        role_mask=8,
        permission_scopes=frozenset({"agentic.admin", "interaction.ask_admin", "validation.run"}),
        idempotency_key=idempotency_key,
        mode=SkillExecutionMode.LIVE,
    )


def test_ask_admin_returns_a_typed_wait_request_without_direct_notification() -> None:
    executor = LiveSkillExecutor(build_default_skill_registry())

    result = asyncio.run(
        executor.execute(
            skill_name="interaction.ask_admin",
            arguments={"request_id": "request-1", "prompt": "Choose a source", "choices": ["A", "B"]},
            context=_context(idempotency_key="ask-admin-1"),
        )
    )

    assert result.output.request.request_id == "request-1"
    assert result.output.request.choices == ["A", "B"]


def test_validation_skills_report_constraint_and_evidence_facts_without_side_effects() -> None:
    executor = LiveSkillExecutor(build_default_skill_registry())
    context = _context()
    constraints = asyncio.run(
        executor.execute(
            skill_name="validation.check_constraints",
            arguments={
                "constraints": [{"constraint_id": "c-1", "description": "Need evidence"}],
                "claimed_resolved_constraint_ids": ["missing"],
                "accepted_candidate_ids": ["candidate-1"],
                "rejected_candidate_ids": ["candidate-1"],
            },
            context=context,
        )
    )
    evidence = asyncio.run(
        executor.execute(
            skill_name="validation.check_evidence",
            arguments={
                "evidence": [
                    {
                        "evidence_id": "e-1",
                        "source_uri": "material://1",
                        "page": 2,
                        "claim_ids": ["claim-1"],
                    },
                    {
                        "evidence_id": "e-1",
                        "source_uri": "material://1",
                        "page": 3,
                        "claim_ids": ["claim-2"],
                    },
                ],
                "required_claim_ids": ["claim-1", "claim-2"],
            },
            context=context,
        )
    )
    artifact = asyncio.run(
        executor.execute(
            skill_name="validation.check_artifact",
            arguments={"artifact": {"artifact_type": "unknown"}},
            context=context,
        )
    )

    assert constraints.output.valid is False
    assert any("unknown resolved constraints" in item for item in constraints.output.violations)
    assert any("accepted/rejected" in item for item in constraints.output.violations)
    assert evidence.output.valid is False
    assert evidence.output.supported_claim_ids == ["claim-1"]
    assert evidence.output.unsupported_claim_ids == ["claim-2"]
    assert evidence.output.invalid_evidence_ids == ["e-1"]
    assert artifact.output.valid is False
    assert artifact.output.violations == ["invalid_artifact"]
