"""veRL-facing AgentLoop interface adapter without a veRL runtime dependency."""

from .agent_loop import AgentLoopRollout, VerlAgentLoopAdapter

__all__ = ["AgentLoopRollout", "VerlAgentLoopAdapter"]
