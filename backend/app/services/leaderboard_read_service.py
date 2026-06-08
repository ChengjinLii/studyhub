from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from threading import RLock
from time import monotonic
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.async_db import async_session_scope
from app.core.config import Settings
from app.repos.read_api_repo import ReadApiRepository


LEADERBOARD_ZONE = ZoneInfo("Asia/Shanghai")


class LeaderboardReadService:
    def __init__(self, settings: Settings, repo: ReadApiRepository) -> None:
        self.settings = settings
        self.repo = repo

    def invalidate_contributor_cache(self) -> None:
        cache, lock = self._contributor_cache_state()
        with lock:
            cache.clear()

    def _contributor_cache_state(self):
        cache = getattr(self, "_contributor_cache", None)
        lock = getattr(self, "_contributor_cache_lock", None)
        if cache is None or lock is None:
            cache = {}
            lock = RLock()
            self._contributor_cache = cache
            self._contributor_cache_lock = lock
        return cache, lock

    def _contributor_cache_ttl_seconds(self) -> int:
        return max(1, int(getattr(self.settings, "public_read_cache_ttl_seconds", 30) or 30))

    def _contributor_cache_get(self, key: tuple[Any, ...]) -> list[dict] | None:
        cache, lock = self._contributor_cache_state()
        now = monotonic()
        with lock:
            entry = cache.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= now:
                cache.pop(key, None)
                return None
            return self._clone_contributor_rows(value)

    def _contributor_cache_set(self, key: tuple[Any, ...], value: list[dict]) -> list[dict]:
        cache, lock = self._contributor_cache_state()
        with lock:
            cache[key] = (monotonic() + self._contributor_cache_ttl_seconds(), self._clone_contributor_rows(value))
        return value

    def _clone_contributor_rows(self, rows: list[dict]) -> list[dict]:
        return [dict(row) for row in rows]

    def get_contributors(self, session: Session, limit: int, period: str | None) -> list[dict]:
        safe_limit = max(1, min(limit, 100))
        normalized = self._compat_normalize_period(period)
        cache_key = ("contributors", "compat" if self.settings.requires_private_env_file else "seed", safe_limit, normalized)
        cached = self._contributor_cache_get(cache_key)
        if cached is not None:
            return cached
        if self.settings.requires_private_env_file:
            return self._contributor_cache_set(
                cache_key,
                self._compat_get_contributors(session=session, limit=safe_limit, period=normalized),
            )
        seed = self.repo.load_seed()
        entries = list((seed.get("leaderboard") or {}).get(normalized, []))
        return self._contributor_cache_set(cache_key, entries[:safe_limit])

    async def get_contributors_async(self, session: Session, limit: int, period: str | None) -> list[dict]:
        if not (self.settings.requires_private_env_file and self.settings.async_read_db_enabled):
            return await asyncio.to_thread(self.get_contributors, session, limit, period)
        async with async_session_scope() as async_session:
            return await self._compat_get_contributors_async(async_session, limit=limit, period=period)

    def _compat_get_contributors(self, session: Session, limit: int, period: str | None) -> list[dict]:
        safe_limit = max(1, min(limit, 100))
        normalized_period = self._compat_normalize_period(period)
        params: dict[str, object] = {"limit": safe_limit}
        where_clauses = [
            "m.deleted_at IS NULL",
            "(m.status IS NULL OR LOWER(m.status) NOT IN ('hidden', 'removed'))",
        ]
        if normalized_period == "week":
            start, end = self._compat_resolve_week_range()
            params.update({"start": start, "end": end})
            where_clauses.extend(["md.created_at >= :start", "md.created_at < :end"])
        elif normalized_period == "month":
            start, end = self._compat_resolve_month_range()
            params.update({"start": start, "end": end})
            where_clauses.extend(["md.created_at >= :start", "md.created_at < :end"])

        rows = session.execute(
            text(
                f"""
                SELECT
                    agg.user_id,
                    COALESCE(NULLIF(u.nickname, ''), u.username) AS username,
                    agg.downloads,
                    u.role_mask
                FROM (
                    SELECT
                        m.uploader_id AS user_id,
                        COUNT(md.id) AS downloads
                    FROM material_downloads md
                    JOIN materials m ON m.id = md.material_id
                    WHERE {' AND '.join(where_clauses)}
                    GROUP BY m.uploader_id
                    ORDER BY COUNT(md.id) DESC, m.uploader_id ASC
                    LIMIT :limit
                ) agg
                JOIN users u ON u.id = agg.user_id
                ORDER BY agg.downloads DESC, agg.user_id ASC
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

    async def _compat_get_contributors_async(self, session, limit: int, period: str | None) -> list[dict]:
        safe_limit = max(1, min(limit, 100))
        normalized_period = self._compat_normalize_period(period)
        cache_key = ("contributors", "compat", safe_limit, normalized_period)
        cached = self._contributor_cache_get(cache_key)
        if cached is not None:
            return cached
        params: dict[str, object] = {"limit": safe_limit}
        where_clauses = [
            "m.deleted_at IS NULL",
            "(m.status IS NULL OR LOWER(m.status) NOT IN ('hidden', 'removed'))",
        ]
        if normalized_period == "week":
            start, end = self._compat_resolve_week_range()
            params.update({"start": start, "end": end})
            where_clauses.extend(["md.created_at >= :start", "md.created_at < :end"])
        elif normalized_period == "month":
            start, end = self._compat_resolve_month_range()
            params.update({"start": start, "end": end})
            where_clauses.extend(["md.created_at >= :start", "md.created_at < :end"])

        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT
                        agg.user_id,
                        COALESCE(NULLIF(u.nickname, ''), u.username) AS username,
                        agg.downloads,
                        u.role_mask
                    FROM (
                        SELECT
                            m.uploader_id AS user_id,
                            COUNT(md.id) AS downloads
                        FROM material_downloads md
                        JOIN materials m ON m.id = md.material_id
                        WHERE {' AND '.join(where_clauses)}
                        GROUP BY m.uploader_id
                        ORDER BY COUNT(md.id) DESC, m.uploader_id ASC
                        LIMIT :limit
                    ) agg
                    JOIN users u ON u.id = agg.user_id
                    ORDER BY agg.downloads DESC, agg.user_id ASC
                    """
                ),
                params,
            )
        ).mappings().all()
        return self._contributor_cache_set(cache_key, [
            {
                "userId": int(row["user_id"]),
                "username": row["username"],
                "downloads": int(row["downloads"]),
                "roleMask": int(row["role_mask"]),
            }
            for row in rows
        ])

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
