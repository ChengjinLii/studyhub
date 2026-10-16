from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .config import Settings
from .schemas import GuardScore, ModelAssessment


class BackendUnavailable(RuntimeError):
    """Sanitized error; never include submission content or upstream error bodies."""


@dataclass(frozen=True)
class DecisionResult:
    model: str
    # Independent rule classifiers can supply answers; Guards only supply native scores.
    answers: dict[str, dict[str, Any]] = field(default_factory=dict)
    usage: dict[str, int] = field(default_factory=dict)
    assessment: ModelAssessment | None = None
    model_revision: str | None = None
    confidence: float | None = None
    scores: list[GuardScore] = field(default_factory=list)


def resolve_device(device: str) -> str:
    if device != "auto":
        return device
    import torch

    if not torch.cuda.is_available():
        return "cpu"
    index = max(range(torch.cuda.device_count()), key=lambda i: torch.cuda.mem_get_info(i)[0])
    return f"cuda:{index}"


class Backend(Protocol):
    name: str
    demo: bool

    def decide(self, state: dict, questions: dict, media: list[dict]) -> DecisionResult: ...
    def ready(self) -> bool: ...
    def close(self) -> None: ...


class DemoBackend:
    name = "demo"
    demo = True

    def decide(self, state: dict, questions: dict, media: list[dict]) -> DecisionResult:
        return DecisionResult(
            "demo-not-a-model", {key: {"type": "noul", "noul": 0.5} for key in questions}
        )

    def ready(self) -> bool:
        return True

    def close(self) -> None:
        pass


class AutoBackend:
    name = "dual-guard"
    demo = False

    def __init__(self, settings: Settings):
        from .qwen_guard import Qwen3GuardBackend
        from .shieldgemma import ShieldGemmaBackend

        self.settings = settings
        self.text = Qwen3GuardBackend(
            Settings.model_validate(
                {
                    **settings.model_dump(),
                    "backend": "qwen3guard",
                    "model": settings.text_model,
                    "model_revision": settings.text_model_revision,
                    "device": settings.text_device,
                }
            )
        )
        self.images = ShieldGemmaBackend(settings)

    def branches(self, has_text: bool, media: list[dict]) -> list[tuple[str, Backend, float]]:
        branches = []
        if has_text:
            branches.append(("text", self.text, self.settings.text_confidence_threshold))
        if media:
            branches.append(("image", self.images, self.settings.image_confidence_threshold))
        return branches

    def ready(self) -> bool:
        return self.text.ready() and self.images.ready()

    def close(self) -> None:
        self.text.close()
        self.images.close()


def make_backend(settings: Settings) -> Backend | AutoBackend:
    if settings.backend == "auto":
        return AutoBackend(settings)
    if settings.backend == "demo":
        return DemoBackend()
    if settings.backend == "qwen3guard":
        from .qwen_guard import Qwen3GuardBackend

        return Qwen3GuardBackend(settings)
    from .shieldgemma import ShieldGemmaBackend

    return ShieldGemmaBackend(settings)
