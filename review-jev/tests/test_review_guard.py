import contextlib
import json
import math
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_review_service import FakeBackend, image_uri

from review_jev.backends import (
    AutoBackend,
    BackendUnavailable,
    DecisionResult,
    make_backend,
    resolve_device,
)
from review_jev.config import DEFAULT_GUARD_MODEL, DEFAULT_ONEJEV_MODEL, Settings
from review_jev.evaluate import evaluate_file, label_metrics
from review_jev.policy import Policy, load_policy
from review_jev.qwen_guard import Qwen3GuardBackend, parse_assessment
from review_jev.schemas import ReviewRequest
from review_jev.server import create_app
from review_jev.service import ReviewService


class NativeBackend:
    name = "qwen3guard"
    demo = False

    def __init__(self, output="Safety: Safe\nCategories: None", confidence=0.99):
        self.output = output
        self.confidence = confidence
        self.calls = []

    def decide(self, state, questions, media):
        self.calls.append((state, questions, media))
        return DecisionResult(
            DEFAULT_GUARD_MODEL,
            {},
            {"input_tokens": 42, "output_tokens": 8},
            parse_assessment(self.output),
            confidence=self.confidence,
        )

    def ready(self):
        return True

    def close(self):
        pass


def request(text="My original calculus notes.", **content):
    return ReviewRequest.model_validate(
        {
            "content": {"text": text, **content},
            "rights": {"basis": "original", "copyrightOwner": "Author", "attested": True},
        }
    )


def test_guard_is_explicit_and_lazy():
    settings = Settings(backend="qwen3guard", device="cpu")
    assert settings.backend == "qwen3guard" and settings.model == DEFAULT_GUARD_MODEL
    assert settings.device == "cpu"
    backend = make_backend(settings)
    assert isinstance(backend, Qwen3GuardBackend)
    assert not backend.ready()
    backend.close()


def test_auto_device_uses_most_available_gpu(monkeypatch):
    cuda = SimpleNamespace(
        is_available=lambda: True,
        device_count=lambda: 2,
        mem_get_info=lambda index: (10, 100) if index == 0 else (50, 100),
    )
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=cuda))
    assert resolve_device("auto") == "cuda:1"
    assert resolve_device("cuda:0") == "cuda:0"
    cuda.is_available = lambda: False
    assert resolve_device("auto") == "cpu"


def test_auto_is_default_and_models_are_lazy():
    settings = Settings()
    assert settings.backend == "auto" and settings.model == DEFAULT_ONEJEV_MODEL
    assert settings.text_model == DEFAULT_GUARD_MODEL
    backend = make_backend(settings)
    assert isinstance(backend, AutoBackend) and not backend.ready()
    assert backend.select([]) is backend.text
    assert backend.select([{"type": "image"}]) is backend.images
    backend.close()


class ImageBackend(FakeBackend):
    name = "torch"

    def decide(self, *args):
        return replace(super().decide(*args), model=DEFAULT_ONEJEV_MODEL)


@pytest.mark.parametrize("text,has_images", [("Notes", False), ("Notes", True), ("", True)])
def test_auto_routing_uses_actual_validated_media(text, has_images):
    backend = AutoBackend(Settings())
    backend.text, backend.images = NativeBackend(), ImageBackend()
    content = {"images": [{"id": "preview", "data": image_uri()}]} if has_images else {}
    result = ReviewService(Settings(), backend).review(request(text=text, **content))
    assert result.model == (DEFAULT_ONEJEV_MODEL if has_images else DEFAULT_GUARD_MODEL)
    assert result.backend == ("torch" if has_images else "qwen3guard")
    assert len(backend.images.calls) == int(has_images)
    assert len(backend.text.calls) == int(not has_images)
    assert result.status == ("completed" if has_images else "partial")
    backend.close()


def test_failed_image_backend_never_falls_back_to_text():
    backend = AutoBackend(Settings(allow_auto_approve=True))
    backend.text, backend.images = NativeBackend(), ImageBackend(failure=True)
    backend.large = ImageBackend(failure=True)
    result = ReviewService(backend.settings, backend).review(
        request(images=[{"id": "preview", "data": image_uri()}])
    )
    assert result.status == "degraded" and result.decision == "manual_review"
    assert result.backend == "torch" and backend.text.calls == []
    backend.close()


def test_invalid_media_fails_before_any_router_backend():
    backend = AutoBackend(Settings())
    backend.text, backend.images = NativeBackend(), ImageBackend()
    from review_jev.media import InvalidImage

    with pytest.raises(InvalidImage):
        ReviewService(Settings(), backend).review(
            request(images=[{"id": "preview", "data": "https://example.org/image.png"}])
        )
    assert backend.text.calls == backend.images.calls == []
    backend.close()


def test_custom_model_does_not_inherit_default_revision():
    settings = Settings(model="custom/vision", text_model="custom/text")
    assert settings.model_revision is None and settings.text_model_revision is None


def test_auto_http_images_are_optional_and_not_required_for_text():
    backend = AutoBackend(Settings(image_backend="onejev-http"))
    assert backend.images.name == "onejev-http"
    backend.close()


def test_readiness_distinguishes_both_routes():
    service = ReviewService()
    with TestClient(create_app(service)) as client:
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json()["backends"] == {"text": False, "images": False, "large": False}
        routing = client.get("/v1/policy").json()["routing"]
        assert routing["text_model"] == DEFAULT_GUARD_MODEL
        assert routing["image_model"] == DEFAULT_ONEJEV_MODEL
        assert routing["text_custom_policy_applied"] is False


@pytest.mark.parametrize("backend", ["onejev-http", "torch"])
def test_legacy_backend_keeps_its_model_default(backend):
    assert Settings(backend=backend).model == DEFAULT_ONEJEV_MODEL
    assert Settings(backend=backend, model="local-model").model == "local-model"


@pytest.mark.parametrize(
    "output,safety,categories",
    [
        ("Safety: Safe\nCategories: None", "Safe", []),
        (
            "Safety: Controversial\nCategories: Copyright Violation",
            "Controversial",
            ["Copyright Violation"],
        ),
        (" Safety: Unsafe\nCategories: Violent, PII\n", "Unsafe", ["Violent", "PII"]),
    ],
)
def test_native_parser(output, safety, categories):
    assessment = parse_assessment(output)
    assert assessment.safety == safety and assessment.categories == categories
    assert assessment.images_evaluated is False
    assert assessment.custom_studyhub_policy_applied is False


@pytest.mark.parametrize(
    "output",
    [
        "",
        "Safe",
        "Safety: Unknown\nCategories: None",
        "Safety: Unsafe\nCategories: None",
        "Safety: Safe\nCategories: Unknown",
        "Safety: Unsafe\nCategories: PII, None",
        "Safety: Unsafe\nCategories: PII, PII",
        "Safety: Safe\nCategories: None\nSECRET",
        "Safety: Safe\nCategories:",
        "Safety: Safe\nCategories: None\nSafety: Unsafe\nCategories: PII",
    ],
)
def test_invalid_labels_fail_closed_without_echo(output):
    with pytest.raises(ValueError) as exc:
        parse_assessment(output)
    assert "SECRET" not in str(exc.value)


def test_safe_native_result_is_partial_and_never_auto_approved():
    service = ReviewService(Settings(allow_auto_approve=True), NativeBackend())
    result = service.review(request())
    assert result.status == "partial" and result.decision == "manual_review"
    assert result.model_assessment.safety == "Safe"
    assert result.copyright.status == "undetermined"
    assert "model_coverage_incomplete" in result.decision_reasons
    assert all(item.risk_probability is None for item in result.findings)
    assert next(f for f in result.findings if f.rule_id == "academic_misconduct").outcome == (
        "unavailable"
    )


def test_custom_policy_cannot_turn_native_labels_into_automatic_approval():
    data = load_policy().model_dump()
    data["rules"] = [rule for rule in data["rules"] if rule["id"] == "sexual_content"]
    service = ReviewService(
        Settings(allow_auto_approve=True), NativeBackend(), Policy.model_validate(data)
    )
    result = service.review(request())
    assert result.status == "partial" and result.decision == "manual_review"
    assert "native_policy_not_studyhub" in result.decision_reasons
    assert result.copyright.status == "undetermined"


@pytest.mark.parametrize(
    "category,rule",
    [
        ("Violent", "graphic_violence"),
        ("PII", "sensitive_personal_data"),
        ("Sexual Content or Sexual Acts", "sexual_content"),
        ("Non-violent Illegal Acts", "illegal_harm"),
        ("Suicide & Self-Harm", "illegal_harm"),
        ("Unethical Acts", "hate_harassment"),
        ("Jailbreak", "review_manipulation"),
        ("Politically Sensitive Topics", "guard_safety"),
    ],
)
def test_native_risks_always_require_review(category, rule):
    service = ReviewService(
        Settings(allow_auto_reject=True), NativeBackend(f"Safety: Unsafe\nCategories: {category}")
    )
    result = service.review(request())
    finding = next(f for f in result.findings if f.rule_id == rule)
    assert finding.outcome == "review" and finding.risk_probability is None
    assert result.decision == "manual_review"


def test_native_copyright_signal_is_not_rights_verification():
    result = ReviewService(
        Settings(), NativeBackend("Safety: Controversial\nCategories: Copyright Violation")
    ).review(request())
    assert result.copyright.status == "needs_review"
    assert result.copyright.declaration_verified is False


def test_mixed_input_keeps_text_signal_and_unavailable_pixels():
    result = ReviewService(Settings(allow_auto_approve=True), NativeBackend()).review(
        request(images=[{"id": "preview", "data": image_uri()}])
    )
    assert result.status == "partial" and result.decision == "manual_review"
    assert result.model_assessment.images_evaluated is False
    finding = next(f for f in result.findings if f.rule_id == "image_moderation")
    assert finding.outcome == "unavailable" and finding.scope == "submission"


def test_image_only_never_loads_text_model(monkeypatch):
    backend = Qwen3GuardBackend(Settings(backend="qwen3guard"))
    monkeypatch.setattr(backend, "_load", lambda: pytest.fail("must not load"))
    result = ReviewService(Settings(allow_auto_approve=True), backend).review(
        request(text="", images=[{"id": "preview", "data": image_uri()}])
    )
    assert result.status == "degraded" and result.model_assessment is None
    assert result.decision == "manual_review"


class FakeInputs(dict):
    def to(self, device):
        return self


def fake_runtime(monkeypatch, output, input_tokens=20):
    calls = {}

    class Tokenizer:
        eos_token_id = 0

        def apply_chat_template(self, messages, **kwargs):
            calls["messages"], calls["template_kwargs"] = messages, kwargs
            return "prompt"

        def __call__(self, prompt, **kwargs):
            calls["tokenizer_kwargs"] = kwargs
            return FakeInputs(input_ids=SimpleNamespace(shape=(1, input_tokens)))

        def decode(self, tokens, **kwargs):
            return "".join(tokens)

    class Model:
        device = "cpu"

        def generate(self, **kwargs):
            calls["generate_kwargs"] = kwargs
            return SimpleNamespace(sequences=[[0] * input_tokens + list(output)], scores=())

        def compute_transition_scores(self, *args, **kwargs):
            calls["score_kwargs"] = kwargs
            return [SimpleNamespace(tolist=lambda: [math.log(0.99)] * len(output))]

    backend = Qwen3GuardBackend(Settings(backend="qwen3guard"))
    backend.tokenizer, backend.model = Tokenizer(), Model()
    monkeypatch.setitem(
        sys.modules, "torch", SimpleNamespace(inference_mode=contextlib.nullcontext)
    )
    return backend, calls


def test_local_inference_follows_guard_template(monkeypatch):
    backend, calls = fake_runtime(monkeypatch, "Safety: Unsafe\nCategories: PII")
    result = ReviewService(Settings(), backend).review(request())
    assert result.model_assessment.categories == ["PII"]
    assert result.usage == {"input_tokens": 20, "output_tokens": 30}
    assert calls["template_kwargs"] == {"tokenize": False}
    assert calls["tokenizer_kwargs"]["truncation"] is False
    assert calls["generate_kwargs"]["do_sample"] is False
    assert calls["generate_kwargs"]["output_scores"] is True
    assert calls["score_kwargs"] == {"normalize_logits": True}
    assert result.confidence == pytest.approx(0.99)
    assert "rights" not in calls["messages"][0]["content"]
    assert backend.ready()
    backend.close()
    assert not backend.ready()


def test_overlong_text_is_not_silently_truncated(monkeypatch):
    backend, calls = fake_runtime(monkeypatch, "Safety: Safe\nCategories: None", 9000)
    result = ReviewService(Settings(), backend).review(request())
    assert result.status == "degraded" and result.decision == "manual_review"
    assert "generate_kwargs" not in calls


def test_invalid_generated_response_is_sanitized(monkeypatch):
    backend, _ = fake_runtime(monkeypatch, "SECRET-CONTENT")
    with pytest.raises(BackendUnavailable) as exc:
        backend.decide({"untrusted_submission": {"text": "notes"}}, {}, [])
    assert "SECRET" not in str(exc.value)


def test_missing_dependencies_fail_closed(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    result = ReviewService().review(request())
    assert result.status == "degraded" and result.decision == "manual_review"


def test_native_api_has_structured_assessment():
    with TestClient(create_app(ReviewService(Settings(), NativeBackend()))) as client:
        result = client.post("/v1/reviews", json=request().model_dump())
        assert result.status_code == 200
        body = result.json()
        assert body["status"] == "partial" and body["model_assessment"]["safety"] == "Safe"
        assert all(f["risk_probability"] is None for f in body["findings"])


def test_label_metrics_have_no_fabricated_calibration():
    metrics = label_metrics([(True, True), (True, False), (False, True), (False, False)])
    assert metrics["precision"] == metrics["recall"] == 0.5
    assert "brier_score" not in metrics and "ece_10_bins" not in metrics


def test_partial_native_results_enter_only_supported_label_metrics(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        json.dumps(
            {
                "request": request().model_dump(),
                "expected_risks": {"sexual_content": False, "third_party_reproduction": True},
                "expected_decision": "manual_review",
            }
        )
        + "\n"
    )
    report = evaluate_file(ReviewService(Settings(), NativeBackend()), path)
    assert report["eligible_model_cases"] == 0 and report["eligible_label_cases"] == 1
    assert report["per_rule_labels"]["sexual_content"]["true_negative"] == 1
    assert report["per_rule_labels"]["third_party_reproduction"]["labeled_checks"] == 0
    assert all(item["labeled_checks"] == 0 for item in report["per_rule"].values())
    assert report["decision_accuracy"] == 1
