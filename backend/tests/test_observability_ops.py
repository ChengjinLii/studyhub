from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api.deps import clear_dependency_caches
from app.core.config import get_settings
from app.core.db import reset_database_runtime
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

    rendered = metrics.render_prometheus(
        SimpleNamespace(app_name="test", environment="test", resolved_build_git_sha="test")
    )

    assert "# TYPE studyhub_http_request_duration_seconds histogram" in rendered
    assert 'studyhub_http_request_duration_seconds_bucket{method="GET",route="/api/materials",le="0.01"} 0' in rendered
    assert 'studyhub_http_request_duration_seconds_bucket{method="GET",route="/api/materials",le="0.025"} 1' in rendered
    assert 'studyhub_http_request_duration_seconds_bucket{method="GET",route="/api/materials",le="0.5"} 2' in rendered
    assert 'studyhub_http_request_duration_seconds_bucket{method="GET",route="/api/materials",le="+Inf"} 2' in rendered
    assert 'studyhub_http_request_duration_seconds_count{method="GET",route="/api/materials"} 2' in rendered
    metrics.clear()
