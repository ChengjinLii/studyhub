from __future__ import annotations

from app.core.config import Settings
from app.services.requests_service import RequestsService


def test_requests_list_pushes_limit_to_visible_public_repo_query() -> None:
    class FakeRequestRepo:
        def __init__(self) -> None:
            self.received = None

        def list_visible_public_requests(self, session, *, sort: str | None, limit: int | None):
            self.received = {"sort": sort, "limit": limit}
            return []

        def find_responded_request_ids(self, session, *, responder_id, request_ids):
            return set()

    repo = FakeRequestRepo()
    service = RequestsService(Settings(environment="test"), read_repo=None, auth_repo=None, material_repo=None, request_repo=repo)  # type: ignore[arg-type]
    service._bootstrap = lambda session: None  # type: ignore[method-assign]

    assert service.list_requests(None, None, sort="hot", limit=7) == []  # type: ignore[arg-type]
    assert repo.received == {"sort": "hot", "limit": 7}
