"""Stable, privacy-bounded state abstractions for trajectory grouping.

The abstract key deliberately records progress shape rather than copying the
full task state or any prompt/artifact payload.  It is useful for training and
evaluation stratification, while the canonical state hash remains the source
of truth for exact replay.
"""

from __future__ import annotations

from .hashing import canonical_hash
from .state import AgentTaskState


def state_abstract_key(state: AgentTaskState) -> str:
    """Return a deterministic, content-bounded abstraction of ``state``.

    This is intentionally not an intent classifier or a workflow label.  A
    policy may create arbitrary plans and select arbitrary registered Skills;
    the key only captures the generic progress topology of that state.
    """

    return canonical_hash(
        {
            "goal_id": state.goal.goal_id,
            "plan": [(step.step_id, step.status.value) for step in state.plan.steps],
            "pending": "user"
            if state.pending_user_request
            else "approval"
            if state.pending_approval
            else "event"
            if state.pending_event
            else None,
            "working_set": {
                "candidate": len(state.working_set.candidate_ids),
                "accepted": len(state.working_set.accepted_ids),
                "rejected": len(state.working_set.rejected_ids),
                "evidence": len(state.working_set.evidence_refs),
            },
            "terminal": state.terminal.status.value if state.terminal else None,
        }
    )
