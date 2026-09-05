"""Configuration contract for strict StudyHub on-policy distillation."""

from __future__ import annotations

from dataclasses import dataclass, field

from training.rl.config import StudyHubAgentGRPOConfig, StudyHubSGLangConfig


@dataclass
class OPDSGLangConfig(StudyHubSGLangConfig):
    # LoRA updates do not reload base weights after SGLang releases them.
    enable_weights_cpu_backup: bool = True


@dataclass
class StudyHubOPDConfig(StudyHubAgentGRPOConfig):
    sglang: OPDSGLangConfig = field(default_factory=OPDSGLangConfig)
    opd_top_k: int = field(default=16)
    opd_student_temperature: float = field(default=0.7)
    opd_teacher_temperature: float = field(default=1.0)
    opd_eps_clip: float = field(default=0.2)
    opd_clip_ratio_c: float = field(default=3.0)
    opd_algorithm: str = field(default="token_reward_direct")
    opd_top_k_strategy: str = field(default="only_stu")
    opd_reward_weight_mode: str = field(default="student_p")
    opd_loss_aggregation: str = field(default="sum-k-then-token-mean")

    def __post_init__(self) -> None:
        super().__post_init__()
        expected = {
            "opd_algorithm": (self.opd_algorithm, "token_reward_direct"),
            "opd_top_k_strategy": (self.opd_top_k_strategy, "only_stu"),
            "opd_reward_weight_mode": (self.opd_reward_weight_mode, "student_p"),
            "opd_loss_aggregation": (
                self.opd_loss_aggregation,
                "sum-k-then-token-mean",
            ),
        }
        mismatches = {
            key: {"actual": actual, "expected": required}
            for key, (actual, required) in expected.items()
            if actual != required
        }
        if mismatches:
            raise ValueError(f"canonical OPD recipe mismatch: {mismatches}")
        if self.opd_top_k != 16:
            raise ValueError("canonical OPD requires top_k=16")
        if self.actor.kl_ctl != 0:
            raise ValueError("canonical OPD requires standard reference KL to be disabled")
        if self.ref is not None:
            raise ValueError("canonical OPD must not configure a reference model")
        if self.teacher is None or self.teacher.engine_type != "train":
            raise ValueError("canonical OPD requires the frozen AReaL train-engine teacher")
        if self.actor.backend != "fsdp:d1":
            raise ValueError("strict two-H100 OPD requires actor backend fsdp:d1")
        if self.rollout.backend != "sglang:d1":
            raise ValueError("strict two-H100 OPD requires rollout backend sglang:d1")
        if self.teacher.train is None or self.teacher.train.backend != "fsdp:d1":
            raise ValueError("strict two-H100 OPD requires teacher backend fsdp:d1")
        if self.gconfig.n_samples != 2:
            raise ValueError("canonical OPD requires exactly two student rollouts per prompt")
        if self.max_turns > 6:
            raise ValueError("canonical OPD pilot is limited to six assistant turns")
        if self.gconfig.max_new_tokens > 4096:
            raise ValueError("canonical OPD pilot is limited to 4096 assistant tokens")
