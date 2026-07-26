from __future__ import annotations

from app.agentic_platform.domain.plan import RetryPolicy
from app.learning_artifacts.services import LearningArtifactService

from ..base import BaseSkill, IdempotencyMode, ObservationTrainingRole, SkillCost, SkillSpec
from ..context import SkillExecutionContext
from .schemas import (
    CheckConstraintsInput,
    CheckConstraintsOutput,
    CheckArtifactInput,
    CheckArtifactOutput,
    CheckEvidenceInput,
    CheckEvidenceOutput,
)


class CheckConstraintsSkill(BaseSkill[CheckConstraintsInput, CheckConstraintsOutput]):
    input_model = CheckConstraintsInput
    output_model = CheckConstraintsOutput
    spec = SkillSpec(
        name="validation.check_constraints",
        version="1.0",
        description="Check claimed constraint resolution and accepted/rejected candidate consistency.",
        input_model="CheckConstraintsInput",
        output_model="CheckConstraintsOutput",
        side_effect="none",
        permission_scopes=["agentic.admin", "validation.run"],
        timeout_seconds=5.0,
        retry_policy=RetryPolicy(max_attempts=1),
        idempotency=IdempotencyMode.PURE,
        observation_training_role=ObservationTrainingRole.HIDDEN,
        environment_adapter="domain_validation",
        reward_hooks=["constraint_delta"],
        cost_model=SkillCost(estimated_context_tokens=150),
    )

    async def execute(self, context: SkillExecutionContext, payload: CheckConstraintsInput) -> CheckConstraintsOutput:
        del context
        known_ids = {constraint.constraint_id for constraint in payload.constraints}
        claimed_ids = set(payload.claimed_resolved_constraint_ids)
        violations: list[str] = []
        unknown_claims = sorted(claimed_ids - known_ids)
        if unknown_claims:
            violations.append(f"unknown resolved constraints: {unknown_claims}")
        candidate_conflicts = sorted(set(payload.accepted_candidate_ids) & set(payload.rejected_candidate_ids))
        if candidate_conflicts:
            violations.append(f"accepted/rejected candidate conflicts: {candidate_conflicts}")
        resolved = [
            constraint.constraint_id
            for constraint in payload.constraints
            if constraint.is_resolved or constraint.constraint_id in claimed_ids
        ]
        unresolved = [constraint.constraint_id for constraint in payload.constraints if constraint.constraint_id not in resolved]
        return CheckConstraintsOutput(
            valid=not violations,
            resolved_constraint_ids=resolved,
            unresolved_constraint_ids=unresolved,
            violations=violations,
        )


class CheckEvidenceSkill(BaseSkill[CheckEvidenceInput, CheckEvidenceOutput]):
    input_model = CheckEvidenceInput
    output_model = CheckEvidenceOutput
    spec = SkillSpec(
        name="validation.check_evidence",
        version="1.0",
        description="Check that required claim IDs have non-duplicated page-level evidence references.",
        input_model="CheckEvidenceInput",
        output_model="CheckEvidenceOutput",
        side_effect="none",
        permission_scopes=["agentic.admin", "validation.run"],
        timeout_seconds=5.0,
        retry_policy=RetryPolicy(max_attempts=1),
        idempotency=IdempotencyMode.PURE,
        observation_training_role=ObservationTrainingRole.HIDDEN,
        environment_adapter="domain_validation",
        reward_hooks=["citation_supported", "citation_invalid"],
        cost_model=SkillCost(estimated_context_tokens=200),
    )

    async def execute(self, context: SkillExecutionContext, payload: CheckEvidenceInput) -> CheckEvidenceOutput:
        del context
        seen_evidence_ids: set[str] = set()
        invalid_evidence_ids: list[str] = []
        available_claim_ids: set[str] = set()
        for evidence in payload.evidence:
            if evidence.evidence_id in seen_evidence_ids:
                invalid_evidence_ids.append(evidence.evidence_id)
                continue
            seen_evidence_ids.add(evidence.evidence_id)
            available_claim_ids.update(evidence.claim_ids)
        supported = [claim_id for claim_id in payload.required_claim_ids if claim_id in available_claim_ids]
        unsupported = [claim_id for claim_id in payload.required_claim_ids if claim_id not in available_claim_ids]
        return CheckEvidenceOutput(
            valid=not unsupported and not invalid_evidence_ids,
            supported_claim_ids=supported,
            unsupported_claim_ids=unsupported,
            invalid_evidence_ids=invalid_evidence_ids,
        )


class CheckArtifactSkill(BaseSkill[CheckArtifactInput, CheckArtifactOutput]):
    input_model = CheckArtifactInput
    output_model = CheckArtifactOutput
    spec = SkillSpec(
        name="validation.check_artifact",
        version="1.0",
        description="Validate a candidate LearningPlan, PracticeSet, MaterialAnalysis, or DailyBrief before persistence.",
        input_model="CheckArtifactInput",
        output_model="CheckArtifactOutput",
        side_effect="none",
        permission_scopes=["agentic.admin", "validation.run"],
        timeout_seconds=5.0,
        retry_policy=RetryPolicy(max_attempts=1),
        idempotency=IdempotencyMode.PURE,
        observation_training_role=ObservationTrainingRole.HIDDEN,
        environment_adapter="learning_artifact_validation",
        reward_hooks=["format_valid", "citation_supported"],
        cost_model=SkillCost(estimated_context_tokens=250),
    )

    async def execute(self, context: SkillExecutionContext, payload: CheckArtifactInput) -> CheckArtifactOutput:
        del context
        review = LearningArtifactService().review(payload.artifact)
        return CheckArtifactOutput(
            valid=review.accepted,
            artifact_type=review.artifact_type,
            artifact_id=review.artifact_id,
            violations=list(review.validation_error_codes),
        )
