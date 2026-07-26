from __future__ import annotations

from app.agentic_platform.domain.plan import RetryPolicy
from app.agentic_platform.domain.state import UserInputRequest

from ..base import BaseSkill, IdempotencyMode, ObservationTrainingRole, SkillCost, SkillSpec
from ..context import SkillExecutionContext
from .schemas import AskAdminInput, AskAdminOutput


class AskAdminSkill(BaseSkill[AskAdminInput, AskAdminOutput]):
    """Create a typed administrator-input request without directly notifying users."""

    input_model = AskAdminInput
    output_model = AskAdminOutput
    spec = SkillSpec(
        name="interaction.ask_admin",
        version="1.0",
        description="Request a bounded clarification or decision from the administrator.",
        input_model="AskAdminInput",
        output_model="AskAdminOutput",
        side_effect="write",
        permission_scopes=["agentic.admin", "interaction.ask_admin"],
        requires_approval=False,
        timeout_seconds=5.0,
        retry_policy=RetryPolicy(max_attempts=1),
        idempotency=IdempotencyMode.KEYED,
        observation_training_role=ObservationTrainingRole.VISIBLE_MASKED,
        environment_adapter="admin_console",
        reward_hooks=["user_questions"],
        cost_model=SkillCost(estimated_context_tokens=120),
    )

    async def execute(self, context: SkillExecutionContext, payload: AskAdminInput) -> AskAdminOutput:
        del context
        return AskAdminOutput(
            request=UserInputRequest(
                request_id=payload.request_id,
                prompt=payload.prompt,
                choices=payload.choices,
                required=payload.required,
                expires_at=payload.expires_at,
            )
        )
