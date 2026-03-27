from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.repos.read_api_repo import ReadApiRepository


LEADERBOARD_ZONE = ZoneInfo("Asia/Shanghai")


class LeaderboardReadService:
    def __init__(self, settings: Settings, repo: ReadApiRepository) -> None:
        self.settings = settings
        self.repo = repo

    def get_contributors(self, session: Session, limit: int, period: str | None) -> list[dict]:
        if self.settings.requires_private_env_file:
            return self._compat_get_contributors(session=session, limit=limit, period=period)
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

    def _compat_get_contributors(self, session: Session, limit: int, period: str | None) -> list[dict]:
        safe_limit = max(1, min(limit, 100))
        normalized_period = self._compat_normalize_period(period)
        params: dict[str, object] = {"limit": safe_limit}
        where_clause = ""
        if normalized_period == "week":
            start, end = self._compat_resolve_week_range()
            params.update({"start": start, "end": end})
            where_clause = "WHERE md.created_at >= :start AND md.created_at < :end"
        elif normalized_period == "month":
            start, end = self._compat_resolve_month_range()
            params.update({"start": start, "end": end})
            where_clause = "WHERE md.created_at >= :start AND md.created_at < :end"

        rows = session.execute(
            text(
                f"""
                SELECT
                    u.id AS user_id,
                    COALESCE(NULLIF(u.nickname, ''), u.username) AS username,
                    COUNT(md.id) AS downloads,
                    u.role_mask
                FROM material_downloads md
                JOIN materials m ON m.id = md.material_id
                JOIN users u ON u.id = m.uploader_id
                {where_clause}
                GROUP BY u.id, u.nickname, u.username, u.role_mask
                ORDER BY COUNT(md.id) DESC, u.id ASC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
        return [
            {
                "userId": int(row["user_id"]),
                "username": row["username"],
                "downloads": int(row["downloads"]),
                "roleMask": int(row["role_mask"]),
            }
            for row in rows
        ]

    def _compat_normalize_period(self, raw: str | None) -> str:
        if not raw:
            return "all"
        normalized = raw.strip().lower()
        if normalized in {"week", "weekly"}:
            return "week"
        if normalized in {"month", "monthly"}:
            return "month"
        return "all"

    def _compat_resolve_week_range(self) -> tuple[datetime, datetime]:
        now = datetime.now(LEADERBOARD_ZONE)
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
        return start.astimezone(UTC).replace(tzinfo=None), end.astimezone(UTC).replace(tzinfo=None)

    def _compat_resolve_month_range(self) -> tuple[datetime, datetime]:
        now = datetime.now(LEADERBOARD_ZONE)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        return start.astimezone(UTC).replace(tzinfo=None), end.astimezone(UTC).replace(tzinfo=None)
