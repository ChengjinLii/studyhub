from __future__ import annotations

from dataclasses import dataclass, field

from areal.api.cli_args import GRPOConfig


@dataclass
class StudyHubAgentGRPOConfig(GRPOConfig):
    workflow: str = field(default="training.rl.hermes_workflow.StudyHubHermesWorkflow")
    eval_workflow: str = field(default="training.rl.hermes_workflow.StudyHubHermesWorkflow")
    max_turns: int = field(default=10)
    environment_root: str = field(default="")
    verifier_root: str = field(default="")
    hermes_checkout: str = field(default="")
    reward_artifact_root: str = field(default="")
