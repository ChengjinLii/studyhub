from __future__ import annotations

from typing import Any

from studyhub_agent.benchmark_v1.hermes_runner import BenchmarkHermesRunner
from studyhub_agent.benchmark_v2.environment import ReplayableAgentEnvironmentV2
from studyhub_agent.benchmark_v2.schema import BenchmarkTaskV2


class BenchmarkHermesRunnerV2(BenchmarkHermesRunner):
    """V2 type adapter around the unchanged pinned Hermes conversation loop."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            **kwargs,
            task_type=BenchmarkTaskV2,
            environment_type=ReplayableAgentEnvironmentV2,
        )
