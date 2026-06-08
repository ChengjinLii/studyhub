from __future__ import annotations

from app.models.auth import AuthUser
from app.services.account_service import AccountService


class _DummyAuthRepo:
    pass


class _CountingReadRepo:
    def __init__(self) -> None:
        self.calls = 0

    def load_seed(self):
        self.calls += 1
        return {
            "users": {
                "7": {
                    "nickname": "Seed Alice",
                    "gradeStages": ["大三"],
                }
            },
            "profileSummary": {
                "7": {
                    "purchases": [{"orderId": 1}, {"orderId": 2}],
                }
            },
            "materials": [
                {"uploaderId": 7, "free": False},
                {"uploaderId": 7, "free": True},
                {"uploaderId": 8, "free": False},
            ],
        }


def test_account_payload_reuses_seed_snapshot_for_counts() -> None:
    read_repo = _CountingReadRepo()
    service = AccountService(_DummyAuthRepo(), read_repo)  # type: ignore[arg-type]
    user = AuthUser(id=7, username="alice", nickname="Alice", verified=True, email_privacy=False)

    payload = service.to_payload(user)

    assert read_repo.calls == 1
    assert payload.nickname == "Alice"
    assert payload.purchaseCount == 2
    assert payload.saleCount == 1
