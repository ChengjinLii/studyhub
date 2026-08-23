"""Deterministic reward contracts for evaluation and training adapters."""

from studyhub_agent.rewards.composite import RewardSignals, evaluate_reward
from studyhub_agent.rewards.schema import REWARD_VERSION, RewardResult

__all__ = ["REWARD_VERSION", "RewardResult", "RewardSignals", "evaluate_reward"]
