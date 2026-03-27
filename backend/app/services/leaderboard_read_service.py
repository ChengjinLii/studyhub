from __future__ import annotations

from app.repos.read_api_repo import ReadApiRepository


class LeaderboardReadService:
    def __init__(self, repo: ReadApiRepository) -> None:
        self.repo = repo

    def get_contributors(self, limit: int, period: str | None) -> list[dict]:
        seed = self.repo.load_seed()
        normalized = (period or "all").strip().lower()
        if normalized in {"weekly", "week"}:
            normalized = "week"
        elif normalized in {"monthly", "month"}:
            normalized = "month"
        else:
            normalized = "all"
        entries = list((seed.get("leaderboard") or {}).get(normalized, []))
        safe_limit = max(1, min(limit, 100))
        return entries[:safe_limit]
