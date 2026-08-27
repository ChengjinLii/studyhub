"""Thin adapters around official external benchmark harnesses."""

from external_benchmarks.adapters.official import OfficialInvocation
from external_benchmarks.adapters.openai_compatible import OpenAICompatiblePolicyAdapter

__all__ = ["OfficialInvocation", "OpenAICompatiblePolicyAdapter"]
