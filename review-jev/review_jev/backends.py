from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

from .config import Settings
from .schemas import ModelAssessment


class BackendUnavailable(RuntimeError):
    """Sanitized backend error; never include submitted content or upstream error bodies."""


@dataclass(frozen=True)
class DecisionResult:
    model: str
    answers: dict[str, dict[str, Any]]
    usage: dict[str, int] = field(default_factory=dict)
    assessment: ModelAssessment | None = None
    model_revision: str | None = None


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


class OneJevHTTPBackend:
    name = "onejev-http"
    demo = False

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.client = httpx.Client(
            base_url=settings.onejev_url,
            timeout=settings.timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def decide(self, state: dict, questions: dict, media: list[dict]) -> DecisionResult:
        payload = {
            "state": state,
            "questions": questions,
            "media": media,
            "model": self.settings.served_model,
        }
        try:
            with self.client.stream("POST", "/v1/systemone", json=payload) as response:
                response.raise_for_status()
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 1024 * 1024:
                        raise BackendUnavailable("backend_response_too_large")
                import json

                body = json.loads(data)
            if not isinstance(body, dict) or not isinstance(body.get("model"), str):
                raise BackendUnavailable("invalid_backend_response")
            return DecisionResult(body["model"], body["answers"], body.get("usage", {}))
        except BackendUnavailable:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise BackendUnavailable("onejev_unavailable_or_invalid_response") from exc

    def ready(self) -> bool:
        try:
            response = self.client.get("/health", timeout=min(2, self.settings.timeout_seconds))
            return response.status_code == 200 and response.json().get("status") == "ok"
        except (httpx.HTTPError, ValueError, AttributeError):
            return False

    def close(self) -> None:
        self.client.close()


class TorchBackend:
    name = "torch"
    demo = False

    def __init__(self, settings: Settings):
        self.settings = settings
        self.engine = None
        self.lock = threading.Lock()

    def _load(self):
        if self.engine is None:
            from qev.calibrate import Calibration
            from qev.mm_engine import MMDecisionEngine, local_model_dir

            # Lazy loading avoids downloading weights in demo/HTTP mode or during API import.
            if self.settings.model_revision and not Path(self.settings.model).exists():
                from huggingface_hub import snapshot_download

                model_path = snapshot_download(
                    self.settings.model,
                    revision=self.settings.model_revision,
                    allow_patterns=["*.json", "*.safetensors", "*.jinja", "*.txt", "*.model"],
                )
            else:
                model_path = local_model_dir(self.settings.model)
            calibration_path = Path(model_path) / "calibration.json"
            calibration = Calibration.load(calibration_path) if calibration_path.exists() else None
            self.engine = MMDecisionEngine(
                model_path,
                device=resolve_device(self.settings.device),
                calibration=calibration,
                allow_local_paths=False,
                max_branch_tokens=self.settings.max_input_tokens,
                max_request_tokens=self.settings.max_input_tokens * 2,
                gpu_preprocess=False,
                cuda_graphs=False,
            )
        return self.engine

    def decide(self, state: dict, questions: dict, media: list[dict]) -> DecisionResult:
        from qev.schema import SystemOneRequest

        try:
            with self.lock:
                engine = self._load()
                request = SystemOneRequest(state=state, questions=questions, media=media)
                response, _ = engine.decide(request, debias=1, debug=False)
            body = response.model_dump()
            return DecisionResult(
                self.settings.model,
                body["answers"],
                body["usage"],
                model_revision=self.settings.model_revision,
            )
        except Exception as exc:
            raise BackendUnavailable("local_model_unavailable") from exc

    def ready(self) -> bool:
        return self.engine is not None

    def close(self) -> None:
        with self.lock:
            self.engine = None


class DemoBackend:
    name = "demo"
    demo = True

    def decide(self, state: dict, questions: dict, media: list[dict]) -> DecisionResult:
        # Neutral synthetic scores cannot be used to approve or reject real submissions.
        return DecisionResult(
            "demo-not-a-model", {key: {"type": "noul", "noul": 0.5} for key in questions}
        )

    def ready(self) -> bool:
        return True

    def close(self) -> None:
        pass


class AutoBackend:
    name = "auto"
    demo = False

    def __init__(self, settings: Settings):
        from .qwen_guard import Qwen3GuardBackend

        self.settings = settings
        text_settings = Settings.model_validate(
            {
                **settings.model_dump(),
                "backend": "qwen3guard",
                "model": settings.text_model,
                "model_revision": settings.text_model_revision,
                "device": settings.text_device,
            }
        )
        self.text = Qwen3GuardBackend(text_settings)
        self.images = (
            TorchBackend(settings)
            if settings.image_backend == "torch"
            else OneJevHTTPBackend(settings)
        )

    def select(self, media: list[dict]) -> Backend:
        # Routing depends on validated media, never filenames or untrusted text claims.
        return self.images if media else self.text

    def decide(self, state: dict, questions: dict, media: list[dict]) -> DecisionResult:
        return self.select(media).decide(state, questions, media)

    def ready(self) -> bool:
        return self.text.ready() and self.images.ready()

    def close(self) -> None:
        self.text.close()
        self.images.close()


def make_backend(settings: Settings) -> Backend:
    if settings.backend == "auto":
        return AutoBackend(settings)
    if settings.backend == "qwen3guard":
        from .qwen_guard import Qwen3GuardBackend

        return Qwen3GuardBackend(settings)
    if settings.backend == "demo":
        return DemoBackend()
    if settings.backend == "torch":
        return TorchBackend(settings)
    return OneJevHTTPBackend(settings)
