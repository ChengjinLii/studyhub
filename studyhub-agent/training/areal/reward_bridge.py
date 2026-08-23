from __future__ import annotations

from typing import Any

from studyhub_agent.rewards import RewardResult


def reward_to_areal(result: RewardResult) -> dict[str, Any]:
    """Translate the frozen reward contract without changing its scalar."""

    return {
        "reward": result.total,
        "reward_components": {
            "task_success": result.task_success,
            "groundedness": result.groundedness,
            "citation": result.citation,
            "tool_quality": result.tool_quality,
            "efficiency": result.efficiency,
        },
        "violations": list(result.violations),
    }
