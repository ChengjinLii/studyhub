from __future__ import annotations

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.decision import AgentDecision
from app.agentic_platform.domain.hashing import canonical_hash
from app.agentic_platform.domain.state import StateDelta

from .budget import has_semantic_state_change


class DuplicateActionAssessment(DomainModel):
    fingerprint: str
    is_duplicate: bool


class NoStateDeltaAssessment(DomainModel):
    has_no_state_delta: bool
    is_void_turn: bool


class DuplicateActionDetector:
    """Records repeated actions for feedback; it does not prohibit retries."""

    @staticmethod
    def fingerprint(decision: AgentDecision) -> str:
        return canonical_hash(
            {
                "action_type": decision.action_type,
                "plan_step_id": decision.plan_step_id,
                "skill_name": decision.skill_name,
                "arguments": decision.arguments,
                "delegate_agent": decision.delegate_agent,
                "task_packet": decision.task_packet,
                "user_request": decision.user_request,
                "approval_request": decision.approval_request,
                "event_wait": decision.event_wait,
                "final_output": decision.final_output,
            }
        )

    def assess(self, decision: AgentDecision, prior_fingerprints: list[str]) -> DuplicateActionAssessment:
        fingerprint = self.fingerprint(decision)
        return DuplicateActionAssessment(fingerprint=fingerprint, is_duplicate=fingerprint in set(prior_fingerprints))


class NoStateDeltaDetector:
    """Makes stalled turns observable without converting them into a hard stop."""

    @staticmethod
    def assess(delta: StateDelta, *, has_observation: bool) -> NoStateDeltaAssessment:
        has_no_state_delta = not has_semantic_state_change(delta)
        return NoStateDeltaAssessment(
            has_no_state_delta=has_no_state_delta,
            is_void_turn=has_no_state_delta and not has_observation,
        )
