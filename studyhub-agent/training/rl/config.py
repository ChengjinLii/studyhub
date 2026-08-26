from __future__ import annotations

from dataclasses import dataclass, field

from areal.api.cli_args import AgentConfig, GRPOConfig, InferenceEngineConfig, SGLangConfig

from training.rl.budget_contract import RUNTIME_MAX_MODEL_TURNS


AGENT_ENGINE_MAX_TOKENS = 4096
AGENT_MAX_TURNS = RUNTIME_MAX_MODEL_TURNS
CONTEXT_FINALIZATION_RATIO = 0.80
CONTEXT_SAFETY_MARGIN_TOKENS = 256


@dataclass
class StudyHubAgentConfig(AgentConfig):
    engine_max_tokens: int | None = AGENT_ENGINE_MAX_TOKENS
    chat_template_type: str = "hf"
    export_style: str = "individual"


@dataclass
class StudyHubInferenceEngineConfig(InferenceEngineConfig):
    agent: StudyHubAgentConfig = field(
        default_factory=lambda: StudyHubAgentConfig(
            agent_cls_path="areal.experimental.openai.proxy.online_agent._OnlineAgent"
        )
    )


@dataclass
class StudyHubSGLangConfig(SGLangConfig):
    """Keep the pinned SGLang runtime within this host's no-nvcc constraints."""

    disable_overlap_schedule: bool = True
    sampling_backend: str | None = "pytorch"
    max_loaded_loras: int = 1
    max_loras_per_batch: int = 1


@dataclass
class StudyHubAgentGRPOConfig(GRPOConfig):
    rollout: StudyHubInferenceEngineConfig = field(
        default_factory=StudyHubInferenceEngineConfig
    )
    sglang: StudyHubSGLangConfig = field(default_factory=StudyHubSGLangConfig)
    workflow: str = field(default="training.rl.hermes_workflow.StudyHubHermesWorkflow")
    eval_workflow: str = field(default="training.rl.hermes_workflow.StudyHubHermesWorkflow")
    max_turns: int = field(default=AGENT_MAX_TURNS)
    environment_root: str = field(default="")
    verifier_root: str = field(default="")
    hermes_checkout: str = field(default="")
    reward_artifact_root: str = field(default="")
    context_finalization_ratio: float = field(default=CONTEXT_FINALIZATION_RATIO)
    context_safety_margin_tokens: int = field(default=CONTEXT_SAFETY_MARGIN_TOKENS)
