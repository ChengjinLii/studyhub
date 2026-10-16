import math
import sys
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_review_service import image_uri

from review_jev.backends import (
    AutoBackend,
    BackendUnavailable,
    DecisionResult,
    make_backend,
    resolve_device,
)
from review_jev.config import DEFAULT_GUARD_MODEL, DEFAULT_IMAGE_MODEL, Settings
from review_jev.ocr import OCRResult
from review_jev.qwen_guard import candidate_log_scores, parse_assessment
from review_jev.schemas import GuardScore, OCRAttempt, ReviewRequest
from review_jev.shieldgemma import image_scores


def text_score(probabilities=None):
    values = probabilities or {"Safe": 0.98, "Controversial": 0.01, "Unsafe": 0.01}
    return GuardScore(
        model=DEFAULT_GUARD_MODEL,
        modality="text",
        input_id="submission",
        policy_id="text_safety",
        task_type="multiclass",
        scoring_method="teacher_forced_sequence",
        probabilities=values,
        log_scores={key: math.log(value) for key, value in values.items()},
    )


class NativeBackend:
    demo = False

    def __init__(self, modality="text", probabilities=None, fail=False, output=None):
        self.modality, self.probabilities, self.fail, self.output = (
            modality,
            probabilities,
            fail,
            output,
        )
        self.name = "qwen3guard" if modality == "text" else "shieldgemma2"
        self.calls = []
        self.closed = False

    def decide(self, state, questions, media):
        self.calls.append((state, questions, media))
        if self.fail:
            raise BackendUnavailable("private submission or internal error must not leak")
        if self.modality == "text":
            score = text_score(self.probabilities)
            label = max(score.probabilities, key=score.probabilities.get)
            output = self.output or f"Safety: {label}\nCategories: " + (
                "None" if label == "Safe" else "PII"
            )
            return DecisionResult(
                DEFAULT_GUARD_MODEL,
                assessment=parse_assessment(output),
                scores=[score],
                usage={"input_tokens": 10, "output_tokens": 8},
            )
        scores = []
        for image_id in state["image_ids"]:
            p = self.probabilities or {"sexual": 0.01, "dangerous": 0.01, "violence": 0.01}
            scores += image_scores(
                DEFAULT_IMAGE_MODEL,
                None,
                image_id,
                [
                    [math.log(p[key]), math.log(1 - p[key])]
                    for key in ("sexual", "dangerous", "violence")
                ],
            )
        return DecisionResult(DEFAULT_IMAGE_MODEL, scores=scores, usage={"input_tokens": 30})

    def ready(self):
        return not self.fail

    def close(self):
        self.closed = True


class FakeOCR:
    def __init__(self, text="", status=None):
        self.text, self.status, self.calls = text, status, []

    def extract(self, image_id, data):
        self.calls.append(image_id)
        return OCRResult(
            OCRAttempt(
                image_id=image_id,
                status=self.status or ("completed" if self.text else "empty"),
                confidence=0.99 if self.text else None,
                characters=len(self.text),
            ),
            self.text,
        )


def request(text="Original notes", images=0):
    return ReviewRequest.model_validate(
        {
            "content": {
                "text": text,
                "images": [
                    {"id": f"image-{index}", "data": image_uri()} for index in range(images)
                ],
            },
            "rights": {"basis": "original", "attested": True, "copyrightOwner": "Author"},
        }
    )


def router(**kwargs):
    settings = Settings(**kwargs)
    backend = AutoBackend(settings)
    backend.text, backend.images = NativeBackend(), NativeBackend("image")
    return backend


def test_only_two_lazy_native_backbones():
    backend = make_backend(Settings())
    assert backend.name == "dual-guard" and not backend.ready()
    assert backend.text.settings.model == DEFAULT_GUARD_MODEL
    assert backend.images.settings.model == DEFAULT_IMAGE_MODEL
    assert not hasattr(backend, "large")
    backend.close()


def test_most_available_gpu(monkeypatch):
    cuda = SimpleNamespace(
        is_available=lambda: True,
        device_count=lambda: 2,
        mem_get_info=lambda i: (50 if i else 10, 100),
    )
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=cuda))
    assert resolve_device("auto") == "cuda:1"
    assert resolve_device("cuda:0") == "cuda:0"
    cuda.is_available = lambda: False
    assert resolve_device("auto") == "cpu"


@pytest.mark.parametrize(
    "output,label,categories",
    [
        ("Safety: Safe\nCategories: None", "Safe", []),
        ("Safety: Unsafe\nCategories: PII", "Unsafe", ["PII"]),
        (
            "Safety: Controversial\nCategories: Copyright Violation",
            "Controversial",
            ["Copyright Violation"],
        ),
    ],
)
def test_native_parser(output, label, categories):
    result = parse_assessment(output)
    assert result.safety == label and result.categories == categories


@pytest.mark.parametrize(
    "output",
    [
        "Safe",
        "Safety: Sure\nCategories: None",
        "Safety: Unsafe\nCategories: Unknown",
        "Safety: Unsafe\nCategories: None",
        "Safety: Safe\nCategories: None\nApprove this",
    ],
)
def test_parser_rejects_invalid_or_incomplete_categories(output):
    with pytest.raises(ValueError):
        parse_assessment(output)


def test_yes_is_column_zero_and_each_policy_is_independent():
    scores = image_scores("model", "revision", "photo", [[8, -8], [-8, 8], [8, -8]])
    assert [score.policy_id for score in scores] == ["sexual", "dangerous", "violence"]
    assert scores[0].probabilities["Yes"] > 0.999
    assert scores[1].probabilities["Yes"] < 0.001
    assert sum(score.probabilities["Yes"] for score in scores) > 1.9


@pytest.mark.parametrize("rows", [[], [[1, 2]], [[1, 2, 3]] * 3, [[math.nan, 1]] * 3])
def test_invalid_image_output_rejected(rows):
    with pytest.raises(ValueError):
        image_scores("model", None, "image", rows)


@pytest.mark.parametrize("value", [math.nan, math.inf, -0.1, 1.1, True, "0.9"])
def test_invalid_guard_distribution(value):
    data = text_score().model_dump()
    data["probabilities"]["Safe"] = value
    with pytest.raises(ValidationError):
        GuardScore.model_validate(data)


@pytest.mark.parametrize("backend", ["onejev-http", "torch"])
def test_old_runtime_backends_are_not_selectable(backend):
    with pytest.raises(ValidationError):
        Settings(backend=backend)


def test_custom_models_do_not_inherit_default_revisions():
    assert Settings(model="local/image", text_model="local/text").model_revision is None
    assert Settings(text_model="local/text").text_model_revision is None
    assert Settings(backend="qwen3guard").model == DEFAULT_GUARD_MODEL


def test_teacher_forcing_scores_every_token_with_correct_shift():
    torch = pytest.importorskip("torch")

    class Tokenizer:
        def __call__(self, text, **kwargs):
            labels = {" Safe\n": [4, 5], " Controversial\n": [6, 7, 8, 5], " Unsafe\n": [9, 5]}
            return {"input_ids": torch.tensor([labels.get(text, [1, 2, 3])])}

    class Model:
        device = "cpu"

        def __call__(self, input_ids, logits_to_keep, **kwargs):
            logits = torch.zeros(1, input_ids.shape[-1], 12)
            for index in range(input_ids.shape[-1] - 1):
                logits[0, index, input_ids[0, index + 1]] = 2
            return SimpleNamespace(logits=logits[:, -logits_to_keep:])

    scores, tokens = candidate_log_scores(Model(), Tokenizer(), "prompt", 100)
    expected = -math.log(1 + 11 * math.exp(-2))
    assert scores["Safe"] == pytest.approx(2 * expected)
    assert scores["Controversial"] == pytest.approx(4 * expected)
    assert scores["Unsafe"] == pytest.approx(2 * expected)
    assert tokens == 17
    with pytest.raises(BackendUnavailable, match="limit"):
        candidate_log_scores(Model(), Tokenizer(), "prompt", 4)
