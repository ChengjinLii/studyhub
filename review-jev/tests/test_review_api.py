import asyncio
import threading

import httpx
from fastapi.testclient import TestClient
from test_review_service import FakeBackend, image_uri

from review_jev.config import Settings
from review_jev.server import BodyLimitMiddleware, create_app
from review_jev.service import ReviewService

REQUEST = {
    "content": {"text": "Study notes"},
    "rights": {"basis": "original", "attested": True, "copyrightOwner": "Author"},
}


def test_review_api_and_policy():
    with TestClient(create_app(settings=Settings(backend="demo"))) as client:
        assert client.get("/health").json()["demo"] is True
        assert client.get("/ready").status_code == 200
        policy = client.get("/v1/policy").json()
        assert policy["allow_auto_approve"] is False
        response = client.post("/v1/reviews", json=REQUEST)
        assert response.status_code == 200
        assert response.json()["status"] == "demo"
        assert response.json()["decision"] == "manual_review"


def test_image_review_api():
    request = {"content": {"images": [{"id": "cover", "data": image_uri()}]}}
    with TestClient(create_app(settings=Settings(backend="demo"))) as client:
        response = client.post("/v1/reviews", json=request)
        assert response.status_code == 200
        assert len(response.json()["image_sha256"]["cover"]) == 64


def test_api_authentication():
    with TestClient(create_app(settings=Settings(backend="demo", api_key="test-secret"))) as client:
        assert client.get("/health").status_code == 200
        assert client.post("/v1/reviews", json=REQUEST).status_code == 401
        assert client.get("/v1/policy").status_code == 401
        response = client.post(
            "/v1/reviews", json=REQUEST, headers={"Authorization": "Bearer test-secret"}
        )
        assert response.status_code == 200


def test_api_validation_does_not_echo_sensitive_input():
    with TestClient(create_app(settings=Settings(backend="demo"))) as client:
        response = client.post("/v1/reviews", json={"content": {"text": "SECRET" * 5000}})
        assert response.status_code == 422
        assert "SECRET" not in response.text
        assert client.post("/v1/reviews", content="{").status_code == 422


def test_invalid_image_returns_422():
    with TestClient(create_app(settings=Settings(backend="demo"))) as client:
        response = client.post(
            "/v1/reviews",
            json={
                "content": {
                    "images": [{"id": "img", "data": "file:///etc/passwd"}],
                }
            },
        )
        assert response.status_code == 422


def test_backend_failure_returns_degraded_review():
    service = ReviewService(Settings(allow_auto_approve=True), FakeBackend(failure=True))
    with TestClient(create_app(service)) as client:
        assert client.get("/ready").status_code == 503
        result = client.post("/v1/reviews", json=REQUEST)
        assert result.status_code == 200
        assert result.json()["decision"] == "manual_review"
        assert result.json()["status"] == "degraded"


def test_body_limits_and_content_encoding():
    app = create_app(settings=Settings(backend="demo"))
    app.add_middleware(BodyLimitMiddleware, limit=128)
    with TestClient(app) as client:
        assert client.post("/v1/reviews", content="x" * 129).status_code == 413
        assert (
            client.post(
                "/v1/reviews", content=b"compressed", headers={"Content-Encoding": "gzip"}
            ).status_code
            == 415
        )


def test_api_overload_does_not_start_second_model_request():
    started, release = threading.Event(), threading.Event()

    class BusyBackend(FakeBackend):
        def decide(self, *args):
            started.set()
            assert release.wait(5)
            return super().decide(*args)

    backend = BusyBackend()
    service = ReviewService(Settings(max_concurrent_reviews=1), backend)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(service)),
            base_url="http://test",
        ) as client:
            first = asyncio.create_task(client.post("/v1/reviews", json=REQUEST))
            try:
                assert await asyncio.to_thread(started.wait, 3)
                second = await client.post("/v1/reviews", json=REQUEST)
                assert second.status_code == 503
            finally:
                release.set()
            assert (await first).status_code == 200
        assert len(backend.calls) == 1

    asyncio.run(run())
