from __future__ import annotations

import json

import pytest

from app.api.deps import clear_dependency_caches, get_admin_agent_run_service, get_auth_repo
from app.core.config import get_settings
from app.core.db import session_scope
from app.models.agentic_runtime import AgentRunStatus
from app.repos.agentic_run_repo import AgentRunRepository
from tests.support import build_auth_headers, seed_read_users


RUNS_PATH = "/api/admin/agent-runs"


@pytest.fixture()
def agentic_platform_enabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STUDYHUB_AGENTIC_PLATFORM_ENABLED", "true")
    get_settings.cache_clear()
    clear_dependency_caches()
    yield
    clear_dependency_caches()
    get_settings.cache_clear()


@pytest.fixture()
def deep_research_enabled(agentic_platform_enabled, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STUDYHUB_DEEP_RESEARCH_ENABLED", "true")
    get_settings.cache_clear()
    clear_dependency_caches()
    yield
    clear_dependency_caches()
    get_settings.cache_clear()


def _set_role(user_id: int, role_mask: int) -> None:
    with session_scope() as session:
        user = get_auth_repo().find_user_by_id(session, user_id)
        assert user is not None
        user.role_mask = role_mask
        get_auth_repo().save_user(session, user)


def _create_waiting_run(client, headers: dict[str, str]) -> tuple[str, str]:
    response = client.post(RUNS_PATH, headers=headers, json={"goal": "Need an administrator decision"})
    assert response.status_code == 200
    run_id = response.json()["data"]["id"]
    with session_scope() as session:
        repository = AgentRunRepository()
        repository.transition_run_status(session, run_id=run_id, target_status=AgentRunStatus.RUNNING)
        wait, created = repository.create_or_get_wait(
            session,
            run_id=run_id,
            wait_type="approval",
            request_payload={"approval_id": "approval-admin-1", "action_summary": "Approve the next safe action."},
            idempotency_key="approval-admin-1",
        )
        assert created is True
        repository.transition_run_status(session, run_id=run_id, target_status=AgentRunStatus.WAITING)
        wait_id = wait.id
    return run_id, wait_id


def test_admin_can_create_refresh_and_stream_a_durable_agent_run(client, auth_service, agentic_platform_enabled) -> None:
    seed_read_users(auth_service)
    headers = build_auth_headers(3, 8)
    payload = {
        "goal": "Compare current calculus materials and prepare an admin preview.",
        "title": "Calculus material review",
        "successCriteria": ["Use internal evidence", "Do not publish to students"],
        "idempotencyKey": "admin-run-create-1",
    }

    created = client.post(RUNS_PATH, headers=headers, json=payload)

    assert created.status_code == 200
    run = created.json()["data"]
    assert run["status"] == "queued"
    assert run["runKind"] == "agent_run"
    assert run["shadowMode"] is True
    assert run["goal"] == payload["goal"]
    assert run["events"][0]["name"] == "run.queued"
    assert "chain_of_thought" not in json.dumps(run, ensure_ascii=False)

    refreshed = client.get(f"{RUNS_PATH}/{run['id']}", headers=headers)
    listing = client.get(RUNS_PATH, headers=headers)
    duplicate = client.post(RUNS_PATH, headers=headers, json=payload)
    stream = client.get(f"{RUNS_PATH}/{run['id']}/events", headers=headers)

    assert refreshed.status_code == 200
    assert refreshed.json()["data"]["id"] == run["id"]
    assert listing.status_code == 200
    assert listing.json()["data"]["items"][0]["id"] == run["id"]
    assert duplicate.status_code == 200
    assert duplicate.json()["data"]["id"] == run["id"]
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "event: run.snapshot" in stream.text
    assert "event: run.queued" in stream.text
    assert "id: 1" in stream.text


def test_sse_reconnect_uses_last_event_id_and_redacts_private_reasoning(client, auth_service, agentic_platform_enabled) -> None:
    seed_read_users(auth_service)
    headers = build_auth_headers(3, 8)
    created = client.post(RUNS_PATH, headers=headers, json={"goal": "Observe safe event payloads"})
    run_id = created.json()["data"]["id"]
    with session_scope() as session:
        run = AgentRunRepository().require_run(session, run_id)
        get_admin_agent_run_service().events.append(
            session,
            run=run,
            name="skill.completed",
            payload={"skill_name": "research.search_internal", "chain_of_thought": "private reasoning", "query": "calculus"},
            idempotency_key="redaction-test",
        )

    initial = client.get(f"{RUNS_PATH}/{run_id}/events", headers=headers)
    reconnected = client.get(f"{RUNS_PATH}/{run_id}/events", headers={**headers, "Last-Event-ID": "2"})

    assert initial.status_code == 200
    assert "private reasoning" not in initial.text
    assert "[redacted]" in initial.text
    assert "calculus" in initial.text
    assert reconnected.status_code == 200
    assert "event: run.snapshot" in reconnected.text
    assert "event: skill.completed" not in reconnected.text


def test_resume_token_is_one_time_and_queues_durable_resume_job(client, auth_service, agentic_platform_enabled) -> None:
    seed_read_users(auth_service)
    headers = build_auth_headers(3, 8)
    run_id, wait_id = _create_waiting_run(client, headers)
    detail = client.get(f"{RUNS_PATH}/{run_id}", headers=headers)
    wait = detail.json()["data"]["waits"][0]

    resumed = client.post(
        f"{RUNS_PATH}/{run_id}/resume",
        headers=headers,
        json={"waitId": wait_id, "resumeToken": wait["resumeToken"], "payload": {"approved": True}},
    )
    repeated = client.post(
        f"{RUNS_PATH}/{run_id}/resume",
        headers=headers,
        json={"waitId": wait_id, "resumeToken": wait["resumeToken"], "payload": {"approved": True}},
    )

    assert resumed.status_code == 200
    resumed_data = resumed.json()["data"]
    assert resumed_data["status"] == "queued"
    assert resumed_data["waits"][0]["status"] == "resolved"
    assert any(job["type"] == "agent_run.resume" for job in resumed_data["jobs"])
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "RESUME_TOKEN_ALREADY_USED"


def test_cancel_requests_a_safe_durable_stop(client, auth_service, agentic_platform_enabled) -> None:
    seed_read_users(auth_service)
    headers = build_auth_headers(3, 8)
    created = client.post(RUNS_PATH, headers=headers, json={"goal": "A task that may be cancelled"})
    run_id = created.json()["data"]["id"]

    cancelled = client.post(f"{RUNS_PATH}/{run_id}/cancel", headers=headers, json={"reason": "Operator changed scope"})

    assert cancelled.status_code == 200
    data = cancelled.json()["data"]
    assert data["status"] == "cancelling"
    assert any(event["name"] == "run.cancel_requested" for event in data["events"])
    assert any(job["type"] == "agent_run.cancel" for job in data["jobs"])


def test_deep_research_is_feature_flagged_and_uses_internal_sources_by_default(client, auth_service, deep_research_enabled) -> None:
    seed_read_users(auth_service)
    headers = build_auth_headers(3, 8)

    response = client.post(
        "/api/admin/deep-research",
        headers=headers,
        json={"question": "Which internal sources explain Fourier transforms for beginners?"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["runKind"] == "deep_research"
    assert data["status"] == "queued"
    assert data["shadowMode"] is True


def test_deep_research_stays_unavailable_when_its_feature_flag_is_off(client, auth_service, agentic_platform_enabled) -> None:
    seed_read_users(auth_service)

    response = client.post(
        "/api/admin/deep-research",
        headers=build_auth_headers(3, 8),
        json={"question": "This must not queue while deep research is disabled."},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "Deep research is disabled"


def test_agentic_control_plane_routes_are_not_enumerated_in_openapi(client, auth_service, agentic_platform_enabled) -> None:
    seed_read_users(auth_service)

    response = client.get("/openapi.json", headers=build_auth_headers(3, 8))

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert RUNS_PATH not in paths
    assert "/api/admin/deep-research" not in paths
    assert "/api/admin/agent-artifacts" not in paths


def test_agentic_run_api_rejects_developer_and_regular_user(client, auth_service, agentic_platform_enabled) -> None:
    seed_read_users(auth_service)
    _set_role(1, 16)

    developer = client.post(RUNS_PATH, headers=build_auth_headers(1, 16), json={"goal": "developer attempt"})
    regular_user = client.post(RUNS_PATH, headers=build_auth_headers(2, 1), json={"goal": "user attempt"})

    assert developer.status_code == 403
    assert developer.json()["error"]["code"] == "Agentic research platform is admin-only"
    assert regular_user.status_code == 403
    assert regular_user.json()["error"]["code"] == "Agentic research platform is admin-only"
