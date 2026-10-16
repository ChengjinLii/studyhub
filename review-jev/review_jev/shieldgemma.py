from __future__ import annotations

import base64
import io
import threading

from PIL import Image

from .backends import BackendUnavailable, DecisionResult, resolve_device
from .config import Settings
from .schemas import GuardScore
from .scoring import softmax

IMAGE_POLICIES = ("sexual", "dangerous", "violence")


def image_scores(
    model: str,
    revision: str | None,
    image_id: str,
    logits: list[list[float]],
    temperature: float = 1,
) -> list[GuardScore]:
    if len(logits) != len(IMAGE_POLICIES) or any(len(row) != 2 for row in logits):
        raise ValueError("invalid image policy output shape")
    return [
        GuardScore(
            model=model,
            model_revision=revision,
            modality="image",
            input_id=image_id,
            policy_id=policy,
            task_type="binary",
            scoring_method="native_yes_no",
            # Actual model order is [Yes, No]; one upstream docstring reverses the index.
            log_scores=dict(zip(("Yes", "No"), row)),
            probabilities=softmax(dict(zip(("Yes", "No"), row)), temperature),
            temperature=temperature,
        )
        for policy, row in zip(IMAGE_POLICIES, logits)
    ]


class ShieldGemmaBackend:
    name = "shieldgemma2"
    demo = False

    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = None
        self.processor = None
        self.lock = threading.Lock()

    def _load(self):
        if self.model is None:
            import torch
            from transformers import AutoProcessor, ShieldGemma2ForImageClassification

            kwargs = {"revision": self.settings.model_revision, "trust_remote_code": False}
            device = resolve_device(self.settings.device)
            processor = AutoProcessor.from_pretrained(self.settings.model, **kwargs)
            processor.tokenizer.padding_side = "left"
            model = (
                ShieldGemma2ForImageClassification.from_pretrained(
                    self.settings.model,
                    dtype=torch.float32 if device == "cpu" else "auto",
                    **kwargs,
                )
                .to(device)
                .eval()
            )
            self.processor, self.model = processor, model

    def decide(self, state: dict, questions: dict, media: list[dict]) -> DecisionResult:
        if not media:
            raise BackendUnavailable("image_backend_no_images")
        image_ids = state.get("image_ids", [])
        if len(image_ids) != len(media) or len(set(image_ids)) != len(image_ids):
            raise BackendUnavailable("image_id_mismatch")
        try:
            import torch

            scores, input_tokens = [], 0
            with self.lock, torch.inference_mode():
                self._load()
                # Bound GPU memory: one image x three policies per forward pass.
                for image_id, item in zip(image_ids, media):
                    raw = base64.b64decode(item["data"].split(",", 1)[1], validate=True)
                    with Image.open(io.BytesIO(raw)) as source:
                        image = source.convert("RGB")
                    inputs = self.processor(
                        images=[image], policies=list(IMAGE_POLICIES), return_tensors="pt"
                    )
                    if inputs["input_ids"].shape[-1] > self.settings.max_input_tokens:
                        raise BackendUnavailable("image_input_limit_exceeded")
                    input_tokens += int(inputs["attention_mask"].sum().item())
                    output = self.model(**inputs.to(self.model.device))
                    scores.extend(
                        image_scores(
                            self.settings.model,
                            self.settings.model_revision,
                            image_id,
                            output.logits.float().cpu().tolist(),
                            self.settings.image_temperature,
                        )
                    )
            return DecisionResult(
                self.settings.model,
                model_revision=self.settings.model_revision,
                scores=scores,
                usage={"input_tokens": input_tokens, "output_tokens": 0},
            )
        except BackendUnavailable:
            raise
        except Exception as exc:
            raise BackendUnavailable("image_model_unavailable_or_invalid_response") from exc

    def ready(self) -> bool:
        return self.model is not None

    def close(self) -> None:
        with self.lock:
            self.model, self.processor = None, None
