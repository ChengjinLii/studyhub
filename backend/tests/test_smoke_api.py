from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_healthz_returns_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/api/healthz")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["data"]["database"] == "ok"
    assert response.json()["data"]["build"]["gitSha"]


def test_session_cookie_round_trip_and_invalid_cookie() -> None:
    client = TestClient(create_app())

    valid_cookie = "%7B%22id%22%3A1%2C%22username%22%3A%22demo_user%22%2C%22nickname%22%3A%22Demo%20User%22%2C%22roleMask%22%3A1%7D"
    ok_response = client.get("/api/session", headers={"Cookie": f"studyhub_user={valid_cookie}"})
    assert ok_response.status_code == 200
    assert ok_response.json()["data"]["user"]["username"] == "demo_user"

    bad_response = client.get("/api/session", headers={"Cookie": "studyhub_user=not-a-json-cookie"})
    assert bad_response.status_code == 401
    assert bad_response.json()["msg"] == "会话已失效"


def test_materials_column_supports_etag_304() -> None:
    client = TestClient(create_app())
    first = client.get("/api/materials/column", params={"topic": "experience", "page": 1, "size": 2})
    assert first.status_code == 200
    etag = first.headers["etag"]
    second = client.get(
        "/api/materials/column",
        params={"topic": "experience", "page": 1, "size": 2},
        headers={"If-None-Match": etag},
    )
    assert second.status_code == 304
    assert second.headers["etag"] == etag
