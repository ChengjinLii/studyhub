from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json
import logging

from fastapi.testclient import TestClient

from app.api.deps import clear_dependency_caches
from app.core.config import get_settings
from app.core.db import reset_database_runtime
from app.core.logging import JsonFormatter, bind_request_context, configure_logging, reset_request_context, sanitize_request_id
from app.core.observability import get_runtime_metrics
from app.main import create_app


def _build_client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("STUDYHUB_ENVIRONMENT", "local-dev")
    monkeypatch.setenv("STUDYHUB_LOCAL_DEV_ROOT_DIR", str(tmp_path / ".local-dev"))
    monkeypatch.setenv("STUDYHUB_JWT_SECRET", "studyhub-fastapi-test-secret-1234567890abcdefghijkl")
    monkeypatch.setenv("STUDYHUB_LOG_FORMAT", "json")
    get_settings.cache_clear()
    clear_dependency_caches()
    reset_database_runtime()
    get_runtime_metrics().clear()
    return TestClient(create_app())


def test_readyz_and_metrics_are_exposed(tmp_path: Path, monkeypatch) -> None:
    with _build_client(tmp_path, monkeypatch) as client:
        assert client.get("/api/healthz").status_code == 200

        ready_response = client.get("/api/readyz")
        assert ready_response.status_code == 200
        ready_payload = ready_response.json()["data"]
        assert ready_payload["status"] == "ok"
        assert ready_payload["checks"]["database"]["status"] == "ok"
        assert ready_payload["checks"]["mail"]["status"] == "ok"
        assert ready_payload["checks"]["storage"]["status"] == "ok"

        metrics_response = client.get("/api/metrics")
        assert metrics_response.status_code == 200
        assert "studyhub_app_info" in metrics_response.text
        assert 'route="/api/healthz"' in metrics_response.text
        assert 'route="/api/readyz"' in metrics_response.text

    clear_dependency_caches()
    reset_database_runtime()
    get_settings.cache_clear()
    get_runtime_metrics().clear()


def test_http_metrics_include_duration_histogram_buckets() -> None:
    metrics = get_runtime_metrics()
    metrics.clear()
    metrics.record_http_request(method="GET", route="/api/materials", status_code=200, duration_seconds=0.012)
    metrics.record_http_request(method="GET", route="/api/materials", status_code=200, duration_seconds=0.28)
    metrics.record_worker_job(job="preview.generate", status="ok", duration_seconds=1.2)
    metrics.record_mcp_tool_call(tool="health.ready", status="ok", duration_seconds=0.04)
    fingerprint = metrics.record_error(
        exception_type="sqlalchemy.exc.OperationalError",
        route="/api/materials/{id}",
        status_code=500,
    )
    metrics.record_ai_agent_run(
        provider="openai-compatible",
        status="model_success",
        pdf_evidence=True,
        memory_context=False,
        course_memory_card=True,
        duration_seconds=2.2,
    )

    rendered = metrics.render_prometheus(
        SimpleNamespace(app_name="test", environment="test", resolved_build_git_sha="test")
    )

    assert "# TYPE studyhub_http_request_duration_seconds histogram" in rendered
    assert 'studyhub_http_request_duration_seconds_bucket{method="GET",route="/api/materials",le="0.01"} 0' in rendered
    assert 'studyhub_http_request_duration_seconds_bucket{method="GET",route="/api/materials",le="0.025"} 1' in rendered
    assert 'studyhub_http_request_duration_seconds_bucket{method="GET",route="/api/materials",le="0.5"} 2' in rendered
    assert 'studyhub_http_request_duration_seconds_bucket{method="GET",route="/api/materials",le="+Inf"} 2' in rendered
    assert 'studyhub_http_request_duration_seconds_count{method="GET",route="/api/materials"} 2' in rendered
    assert 'studyhub_worker_job_duration_seconds_bucket{job="preview.generate",status="ok",le="2.5"} 1' in rendered
    assert 'studyhub_mcp_tool_duration_seconds_bucket{tool="health.ready",status="ok",le="0.05"} 1' in rendered
    assert len(fingerprint) == 12
    assert (
        f'studyhub_errors_total{{fingerprint="{fingerprint}",kind="sqlalchemy.exc.operationalerror",'
        'route="/api/materials/{id}",status_code="500"} 1'
    ) in rendered
    assert (
        'studyhub_ai_agent_run_duration_seconds_bucket{provider="openai-compatible",status="model_success",'
        'pdf_evidence="yes",memory_context="no",course_memory_card="yes",le="2.5"} 1'
    ) in rendered
    metrics.clear()


def test_json_formatter_emits_stable_structured_context() -> None:
    configure_logging(
        "INFO",
        log_format="json",
        service_name="studyhub-test",
        environment="test",
        build_git_sha="abc1234",
    )
    tokens = bind_request_context(request_id="rid-1", method="POST", path="/api/session")
    try:
        record = logging.getLogger("studyhub.test").makeRecord(
            "studyhub.test",
            logging.INFO,
            __file__,
            1,
            "Login attempt",
            (),
            None,
            extra={
                "event": "auth_login",
                "status_code": 401,
                "duration_ms": 12.5,
                "client_ip": "203.0.113.10",
                "token": "should-not-leak",
            },
        )
        formatter = JsonFormatter()
        payload = json.loads(formatter.format(record))
    finally:
        reset_request_context(tokens)

    assert payload["service.name"] == "studyhub-test"
    assert payload["service.version"] == "abc1234"
    assert payload["deployment.environment"] == "test"
    assert payload["severityText"] == "INFO"
    assert payload["request.id"] == "rid-1"
    assert payload["http.request.method"] == "POST"
    assert payload["url.path"] == "/api/session"
    assert payload["http.response.status_code"] == 401
    assert payload["duration.ms"] == 12.5
    assert payload["client.address"] == "203.0.113.10"
    assert payload["attributes"]["token"] == "[REDACTED]"


def test_request_id_header_is_sanitized_in_response(tmp_path: Path, monkeypatch) -> None:
    with _build_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/healthz", headers={"x-request-id": "bad id\nwith spaces and a very long suffix" * 5})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == sanitize_request_id("bad id\nwith spaces and a very long suffix" * 5)
    assert "\n" not in response.headers["x-request-id"]
    assert len(response.headers["x-request-id"]) <= 96
