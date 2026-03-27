from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.models.auth import AuthUser


ROLE_ADMIN = 8
ROLE_DEVELOPER = 16
DEFAULT_OUTPUT_TIMEZONE = ZoneInfo("Asia/Shanghai")


def parse_iso_datetime(value: str | None) -> datetime:
    if not value:
        return datetime(1970, 1, 1, tzinfo=UTC)
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def clamp_limit(limit: int | None, *, max_value: int = 100) -> int | None:
    if limit is None or limit <= 0:
        return None
    return max(1, min(limit, max_value))


def paginate_one_based(items: list[dict[str, Any]], *, page: int, size: int, max_size: int = 100) -> tuple[list[dict[str, Any]], dict[str, int]]:
    safe_page = max(page, 1)
    safe_size = max(1, min(size, max_size))
    start = (safe_page - 1) * safe_size
    end = start + safe_size
    return items[start:end], {"page": safe_page, "size": safe_size, "total": len(items)}


def paginate_zero_based(items: list[dict[str, Any]], *, page: int, size: int, max_size: int = 100) -> tuple[list[dict[str, Any]], dict[str, int]]:
    safe_page = max(page, 0)
    safe_size = max(1, min(size, max_size))
    start = safe_page * safe_size
    end = start + safe_size
    return items[start:end], {"page": safe_page, "size": safe_size, "total": len(items)}


def parse_grade_stages(value: str | None) -> list[str]:
    if not value:
        return []
    return [item for item in (part.strip() for part in value.split(",")) if item]


def has_role(role_mask: int | None, role_bit: int) -> bool:
    return role_mask is not None and (role_mask & role_bit) == role_bit


def unlimited_free_download(role_mask: int | None) -> bool:
    return has_role(role_mask, ROLE_ADMIN) or has_role(role_mask, ROLE_DEVELOPER)


def build_payout_qr_url(user_id: int | None, payout_qr_key: str | None) -> str | None:
    if not user_id or not payout_qr_key:
        return None
    return f"/api/users/{user_id}/payout-qr/image"


def serialize_user_snapshot(seed_user: dict[str, Any] | None, auth_user: AuthUser | None) -> dict[str, Any]:
    base = dict(seed_user or {})
    if auth_user is not None:
        base.update(
            {
                "id": auth_user.id,
                "username": auth_user.username,
                "nickname": auth_user.nickname,
                "signature": auth_user.signature,
                "school": auth_user.school,
                "college": auth_user.college,
                "major": auth_user.major,
                "gradeStages": parse_grade_stages(auth_user.grade_stages),
                "avatar": auth_user.avatar,
                "email": auth_user.email,
                "emailPrivacy": bool(auth_user.email_privacy),
                "legendaryContributorUntil": auth_user.legendary_contributor_until.isoformat()
                if auth_user.legendary_contributor_until
                else None,
                "roleMask": auth_user.role_mask,
                "freeDownloadQuota": auth_user.free_download_quota,
                "verified": bool(auth_user.verified),
                "payoutQrKey": auth_user.payout_qr_key,
                "payoutQrUrl": build_payout_qr_url(auth_user.id, auth_user.payout_qr_key),
            }
        )
    if "gradeStages" not in base or base["gradeStages"] is None:
        base["gradeStages"] = []
    return base


def duration_to_iso(delta: timedelta) -> str:
    if delta.total_seconds() <= 0:
        return "PT0S"
    total_seconds = int(delta.total_seconds())
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts: list[str] = ["P"]
    if days:
        parts.append(f"{days}D")
    if hours or minutes or seconds:
        parts.append("T")
        if hours:
            parts.append(f"{hours}H")
        if minutes:
            parts.append(f"{minutes}M")
        if seconds:
            parts.append(f"{seconds}S")
    if parts == ["P"]:
        return "PT0S"
    return "".join(parts)


def serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=DEFAULT_OUTPUT_TIMEZONE)
    return normalized.isoformat()
