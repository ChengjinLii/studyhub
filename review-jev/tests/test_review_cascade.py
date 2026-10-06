import json
import math
import sys
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_review_guard import NativeBackend, request
from test_review_service import FakeBackend, image_uri

from review_jev.backends import AutoBackend, BackendUnavailable, OneJevHTTPBackend
from review_jev.config import (
    DEFAULT_GUARD_MODEL,
    DEFAULT_LARGE_MODEL,
    DEFAULT_LARGE_REVISION,
    DEFAULT_ONEJEV_MODEL,
    Settings,
)
from review_jev.qwen_guard import generation_confidence
from review_jev.server import create_app
from review_jev.service import ReviewService
from review_jev.smoke import verify


class RuleBackend(FakeBackend):
    name = "torch"

    def __init__(self, model, overrides=None, failure=False):
        super().__init__(overrides, failure)
        self.settings = Settings(backend="torch", model=model)

    def decide(self, *args):
        return replace(super().decide(*args), model=self.settings.model)


def service(confidence=0.99, medium=None, large=None, **options):
    settings = Settings(**options)
    backend = AutoBackend(settings)
    backend.text = NativeBackend(confidence=confidence)
    backend.images = medium or RuleBackend(DEFAULT_ONEJEV_MODEL)
    backend.large = large or RuleBackend(DEFAULT_LARGE_MODEL)
    return ReviewService(settings, backend)


def test_confident_text_stops_at_guard():
    app = service(allow_auto_approve=True)
    result = app.review(request())
    assert result.model == DEFAULT_GUARD_MODEL and result.confidence == 0.99
    assert [item.tier for item in result.model_attempts] == ["0.6b"]
    assert result.model_attempts[0].outcome == "accepted"
    assert app.backend.images.calls == app.backend.large.calls == []
    assert result.status == "partial" and result.decision == "manual_review"


@pytest.mark.parametrize(
    "confidence,reason", [(0.6, "low_confidence"), (None, "confidence_missing")]
)
def test_uncertain_text_escalates_to_4b(confidence, reason):
    app = service(confidence, allow_auto_approve=True)
    result = app.review(request())
    assert result.decision == "approve" and result.model == DEFAULT_ONEJEV_MODEL
    assert [item.tier for item in result.model_attempts] == ["0.6b", "4b"]
    assert result.model_attempts[0].escalation_reason == reason
    assert result.model_attempts[0].model_assessment.safety == "Safe"
    assert result.model_assessment is None
    assert result.confidence == pytest.approx(0.99)
    assert result.usage == {"input_tokens": 142, "output_tokens": 8}
    assert len(result.findings) == 11 and app.backend.large.calls == []
    assert app.backend.text.calls[0] == app.backend.images.calls[0]


def test_4b_uncertainty_escalates_to_9b_and_keeps_trace():
    medium = RuleBackend(DEFAULT_ONEJEV_MODEL, {"sexual_content": 0.5})
    app = service(0.6, medium=medium, allow_auto_approve=True)
    result = app.review(request())
    assert result.model == DEFAULT_LARGE_MODEL and result.decision == "approve"
    assert [item.tier for item in result.model_attempts] == ["0.6b", "4b", "9b"]
    assert [item.outcome for item in result.model_attempts] == [
        "escalated",
        "escalated",
        "accepted",
    ]
    assert result.model_attempts[1].confidence == 0.5
    assert result.model_attempts[1].confidence_method == "rule_probability"
    assert result.usage == {"input_tokens": 242, "output_tokens": 8}
    assert app.backend.images.calls[0] == app.backend.large.calls[0]
    assert next(f for f in result.findings if f.rule_id == "sexual_content").outcome == "clear"
    assert (
        next(f for f in result.model_attempts[1].findings if f.rule_id == "sexual_content").outcome
        == "review"
    )


def test_uncertain_9b_forces_manual_even_with_both_auto_gates():
    medium = RuleBackend(DEFAULT_ONEJEV_MODEL, {"sexual_content": 0.5})
    large = RuleBackend(DEFAULT_LARGE_MODEL, {"sexual_content": 0.99, "illegal_harm": 0.5})
    app = service(0.6, medium, large, allow_auto_approve=True, allow_auto_reject=True)
    result = app.review(request())
    assert result.model == DEFAULT_LARGE_MODEL and result.confidence == 0.5
    assert result.decision == "manual_review"
    assert result.decision_reasons[0] == "low_confidence_after_escalation"
    assert result.model_attempts[-1].outcome == "manual_review"
    assert result.model_attempts[-1].escalation_reason == "low_confidence"
    assert len(large.calls) == 1


def test_confident_9b_risk_respects_rejection_gate():
    medium = RuleBackend(DEFAULT_ONEJEV_MODEL, {"sexual_content": 0.5})
    large = RuleBackend(DEFAULT_LARGE_MODEL, {"sexual_content": 0.99})
    result = service(0.6, medium, large, allow_auto_reject=True).review(request())
    assert result.model == DEFAULT_LARGE_MODEL and result.decision == "reject"
    assert result.model_attempts[-1].outcome == "accepted"


@pytest.mark.parametrize("text", ["", "Notes"])
def test_images_start_at_4b_and_preserve_all_pixels_for_9b(text):
    app = service(medium=RuleBackend(DEFAULT_ONEJEV_MODEL, {"readable_content": 0.5}))
    result = app.review(
        request(
            text=text,
            images=[{"id": "page1", "data": image_uri()}, {"id": "page2", "data": image_uri()}],
        )
    )
    assert app.backend.text.calls == []
    assert result.model == DEFAULT_LARGE_MODEL
    assert [item.tier for item in result.model_attempts] == ["4b", "9b"]
    assert len(app.backend.large.calls[0][2]) == 2
    assert app.backend.large.calls[0] == app.backend.images.calls[0]
    assert set(result.image_sha256) == {"page1", "page2"}


def test_confident_4b_image_stops_without_loading_9b():
    app = service()
    result = app.review(request(images=[{"id": "page", "data": image_uri()}]))
    assert [item.tier for item in result.model_attempts] == ["4b"]
    assert app.backend.large.calls == app.backend.text.calls == []


def test_failed_4b_image_escalates_without_text_fallback():
    app = service(medium=RuleBackend(DEFAULT_ONEJEV_MODEL, failure=True))
    result = app.review(request(images=[{"id": "page", "data": image_uri()}]))
    assert result.status == "completed" and result.model == DEFAULT_LARGE_MODEL
    assert app.backend.text.calls == []
    assert result.model_attempts[0].escalation_reason == "backend_unavailable"
    assert "secret" not in result.model_dump_json()


def test_failed_9b_keeps_last_valid_evidence_but_forces_manual():
    app = service(
        0.6,
        RuleBackend(DEFAULT_ONEJEV_MODEL, {"sexual_content": 0.5}),
        RuleBackend(DEFAULT_LARGE_MODEL, failure=True),
        allow_auto_approve=True,
    )
    result = app.review(request())
    assert result.status == "degraded" and result.decision == "manual_review"
    assert "model_unavailable" in result.decision_reasons
    assert result.model == DEFAULT_ONEJEV_MODEL and len(result.findings) == 11
    assert result.model_attempts[-1].model == DEFAULT_LARGE_MODEL
    assert result.model_attempts[-1].outcome == "unavailable"
    assert result.usage == {"input_tokens": 142, "output_tokens": 8}


def test_all_models_unavailable_are_manual_and_sanitized():
    app = service(
        medium=RuleBackend(DEFAULT_ONEJEV_MODEL, failure=True),
        large=RuleBackend(DEFAULT_LARGE_MODEL, failure=True),
        allow_auto_approve=True,
    )

    class FailedGuard(NativeBackend):
        def decide(self, *args):
            raise BackendUnavailable("private content secret")

    app.backend.text = FailedGuard()
    result = app.review(request())
    assert result.status == "degraded" and result.decision == "manual_review"
    assert result.confidence is None and len(result.model_attempts) == 3
    assert all(f.outcome == "unavailable" for f in result.findings)
    assert "secret" not in result.model_dump_json()


@pytest.mark.parametrize("confidence", [float("nan"), float("inf"), -0.1, 1.1, True, "0.9"])
def test_invalid_guard_confidence_escalates_without_serializing_it(confidence):
    result = service(confidence, allow_auto_approve=True).review(request())
    assert result.model == DEFAULT_ONEJEV_MODEL and result.decision == "approve"
    assert result.model_attempts[0].escalation_reason == "backend_unavailable"
    assert "NaN" not in result.model_dump_json()


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -0.1, 1.1, True, "0.9"])
def test_invalid_4b_probability_escalates_to_9b(score):
    result = service(0.6, RuleBackend(DEFAULT_ONEJEV_MODEL, {"sexual_content": score})).review(
        request()
    )
    assert result.model == DEFAULT_LARGE_MODEL
    assert result.model_attempts[1].escalation_reason == "backend_unavailable"


def test_incomplete_9b_result_forces_manual_and_preserves_valid_4b_findings():
    class IncompleteBackend(RuleBackend):
        def decide(self, *args):
            result = super().decide(*args)
            del result.answers["sexual_content"]
            return result

    result = service(
        0.6,
        RuleBackend(DEFAULT_ONEJEV_MODEL, {"sexual_content": 0.5}),
        IncompleteBackend(DEFAULT_LARGE_MODEL),
        allow_auto_approve=True,
    ).review(request())
    assert result.decision == "manual_review" and result.status == "degraded"
    assert result.model_attempts[-1].escalation_reason == "backend_unavailable"
    assert len(result.findings) == 11


def test_invalid_decision_object_escalates_instead_of_crashing():
    class InvalidBackend(RuleBackend):
        def decide(self, *args):
            return None

    result = service(0.6, InvalidBackend(DEFAULT_ONEJEV_MODEL)).review(request())
    assert result.model == DEFAULT_LARGE_MODEL
    assert result.model_attempts[1].escalation_reason == "backend_unavailable"


def test_native_controversial_escalates_even_with_confident_label():
    app = service()
    app.backend.text = NativeBackend("Safety: Controversial\nCategories: Copyright Violation")
    result = app.review(request())
    assert result.model == DEFAULT_ONEJEV_MODEL
    assert result.model_attempts[0].escalation_reason == "native_controversial"


def test_threshold_uses_raw_probability_without_rounding_up():
    result = service(0.85).review(request())
    assert len(result.model_attempts) == 1
    result = service(0.8499999).review(request())
    assert len(result.model_attempts) == 2
    medium = RuleBackend(DEFAULT_ONEJEV_MODEL, {"sexual_content": 0.1500001})
    result = service(0.6, medium).review(request())
    assert result.model == DEFAULT_LARGE_MODEL


def test_configured_thresholds_apply_per_stage():
    medium = RuleBackend(DEFAULT_ONEJEV_MODEL, {"sexual_content": 0.2})
    result = service(
        0.9, medium, text_confidence_threshold=0.95, image_confidence_threshold=0.75
    ).review(request())
    assert [attempt.confidence_threshold for attempt in result.model_attempts] == [0.95, 0.75]
    assert result.model == DEFAULT_ONEJEV_MODEL


def test_cascade_disabled_keeps_explicit_single_stage_behavior():
    app = service(0.6, cascade_enabled=False)
    result = app.review(request())
    assert len(result.model_attempts) == 1 and result.model == DEFAULT_GUARD_MODEL
    assert result.model_attempts[0].confidence_threshold is None
    assert app.backend.images.calls == app.backend.large.calls == []


def test_close_includes_unused_large_backend():
    app = service()
    closed = []
    for name in ("text", "images", "large"):
        getattr(app.backend, name).close = lambda name=name: closed.append(name)
    app.close()
    assert closed == ["text", "images", "large"]


def test_copyright_checks_survive_escalation():
    app = service(0.6, allow_auto_approve=True)
    submission = request()
    submission.rights.basis = "unknown"
    result = app.review(submission)
    assert result.model == DEFAULT_ONEJEV_MODEL
    assert result.decision == "manual_review" and "rights_declaration_missing" in (
        result.decision_reasons
    )


def test_api_reports_cascade_and_policy_configuration():
    with TestClient(create_app(service(0.6))) as client:
        result = client.post("/v1/reviews", json=request().model_dump())
        assert result.status_code == 200
        assert result.json()["model_attempts"][0]["escalation_reason"] == "low_confidence"
        routing = client.get("/v1/policy").json()["routing"]
        assert routing["cascade_enabled"] is True and routing["large_model"] == DEFAULT_LARGE_MODEL
        assert routing["confidence_thresholds"] == {"0.6b": 0.85, "4b": 0.85, "9b": 0.85}


def test_9b_backend_has_separate_identity_revision_device_and_endpoint():
    settings = Settings(large_backend="onejev-http", large_device="cuda:2")
    backend = AutoBackend(settings)
    try:
        assert backend.large.settings.model == DEFAULT_LARGE_MODEL
        assert backend.large.settings.model_revision == DEFAULT_LARGE_REVISION
        assert backend.large.settings.device == "cuda:2"
        assert str(backend.large.client.base_url) == "http://127.0.0.1:8002"
        assert not backend.large.ready()
    finally:
        backend.close()


def test_9b_http_sends_original_questions_and_media_to_configured_service():
    app = service(0.6, RuleBackend(DEFAULT_ONEJEV_MODEL, {"sexual_content": 0.5}))

    def handle(incoming):
        body = json.loads(incoming.content)
        assert body["model"] == "large-review" and body["media"] == []
        assert body["state"] == app.backend.images.calls[0][0]
        answers = {
            key: {"type": "noul", "noul": 0.99 if key == "readable_content" else 0.01}
            for key in body["questions"]
        }
        return httpx.Response(200, json={"model": DEFAULT_LARGE_MODEL, "answers": answers})

    app.backend.large = OneJevHTTPBackend(
        Settings(model=DEFAULT_LARGE_MODEL, served_model="large-review"),
        transport=httpx.MockTransport(handle),
    )
    try:
        result = app.review(request())
        assert result.model == DEFAULT_LARGE_MODEL and result.backend == "onejev-http"
        assert result.model_attempts[-1].tier == "9b"
    finally:
        app.close()


def test_custom_large_model_does_not_inherit_default_revision(monkeypatch):
    assert Settings(large_model="custom/reviewer").large_model_revision is None
    monkeypatch.setenv("REVIEW_JEV_CASCADE_ENABLED", "false")
    monkeypatch.setenv("REVIEW_JEV_LARGE_MODEL", "custom/reviewer")
    monkeypatch.setenv("REVIEW_JEV_LARGE_CONFIDENCE_THRESHOLD", "0.9")
    configured = Settings.from_env()
    assert not configured.cascade_enabled and configured.large_model_revision is None
    assert configured.large_confidence_threshold == 0.9


def test_cli_cascade_flags_and_custom_revision(monkeypatch, capsys):
    from review_jev import cli

    configured = []

    def factory(settings):
        configured.append(settings)
        return ReviewService(settings, FakeBackend())

    monkeypatch.setattr(cli, "ReviewService", factory)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "review-jev",
            "review",
            str(Path(__file__).resolve().parents[1] / "examples/original-notes.json"),
            "--no-cascade-enabled",
            "--text-confidence-threshold",
            "0.9",
            "--large-model",
            "custom/reviewer",
            "--large-backend",
            "onejev-http",
            "--large-onejev-url",
            "http://127.0.0.1:8003",
        ],
    )
    cli.main()
    assert configured[0].cascade_enabled is False
    assert configured[0].text_confidence_threshold == 0.9
    assert configured[0].large_model_revision is None
    assert configured[0].large_onejev_url == "http://127.0.0.1:8003"
    assert json.loads(capsys.readouterr().out)["decision"] == "manual_review"


def test_smoke_accepts_valid_escalated_routing_and_records_confidence():
    submission = request()
    response = service(0.6, RuleBackend(DEFAULT_ONEJEV_MODEL, {"sexual_content": 0.5})).review(
        submission
    )
    row = verify(submission, response)
    assert row["model"] == DEFAULT_LARGE_MODEL
    assert [attempt["tier"] for attempt in row["model_attempts"]] == ["0.6b", "4b", "9b"]


def test_readiness_does_not_require_unused_lazy_9b():
    app = service()
    app.backend.large.ready = lambda: False
    with TestClient(create_app(app)) as client:
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json()["backends"] == {"text": True, "images": True, "large": False}


@pytest.mark.parametrize("threshold", [0.5, -1, 1.1, float("nan"), float("inf")])
@pytest.mark.parametrize(
    "field",
    ["text_confidence_threshold", "image_confidence_threshold", "large_confidence_threshold"],
)
def test_invalid_thresholds_are_rejected(field, threshold):
    with pytest.raises(ValidationError):
        Settings(**{field: threshold})


def test_guard_confidence_uses_label_tokens_not_template_certainty():
    output = "Safety: Safe\nCategories: None"
    log_probabilities = [math.log(0.999)] * len(output)
    log_probabilities[output.index("Safe", len("Safety: "))] = math.log(0.6)
    assert generation_confidence(
        output, list(range(1, len(output) + 1)), log_probabilities
    ) == pytest.approx(0.6)
    log_probabilities = [math.log(0.99)] * len(output)
    log_probabilities[0] = math.log(0.01)
    assert generation_confidence(
        output, list(range(1, len(output) + 1)), log_probabilities
    ) == pytest.approx(0.99)


def test_guard_confidence_detects_uncertain_category():
    output = "Safety: Unsafe\nCategories: PII"
    log_probabilities = [math.log(0.99)] * len(output)
    log_probabilities[-1] = math.log(0.4)
    assert generation_confidence(
        output, list(range(1, len(output) + 1)), log_probabilities
    ) == pytest.approx(0.4)


@pytest.mark.parametrize("offsets,logs", [([], []), ([10], [-0.1]), ([29], [0.1])])
def test_missing_or_invalid_generation_scores_are_not_fabricated(offsets, logs):
    assert generation_confidence("Safety: Safe\nCategories: None", offsets, logs) is None
