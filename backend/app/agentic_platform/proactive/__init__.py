"""Event-driven, administrator-only Shadow Mode for proactive agents.

This package owns durable trigger delivery and worker mechanics.  It does not
encode a fixed general-agent action loop: policy/runtime bindings remain free
to choose their own typed actions inside a durable AgentJob.
"""

from .dispatcher import ProactiveDispatchResult, ProactiveDispatcher
from .jobs import ProactiveAgentWorker
from .outbox import AgentOutboxLeaseLostError, AgentOutboxRepository
from .triggers import ProactiveTriggerService, ProactiveTriggerType

__all__ = [
    "AgentOutboxLeaseLostError",
    "AgentOutboxRepository",
    "ProactiveAgentWorker",
    "ProactiveDispatchResult",
    "ProactiveDispatcher",
    "ProactiveTriggerService",
    "ProactiveTriggerType",
]
