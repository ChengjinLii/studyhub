from __future__ import annotations

from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.services.read_support import clamp_limit, compat_timestamp


def compat_load_hidden_early_exit_request_ids(
    session: Session,
    request_ids: list[int],
    *,
    paid_contribution_statuses: tuple[str, ...],
    early_exit_refund_type: str,
    success_refund_status: str,
) -> set[int]:
    if not request_ids:
        return set()
    paid_stmt = text(
        """
        SELECT request_id, COUNT(*) AS cnt
        FROM material_request_contributions
        WHERE request_id IN :request_ids
          AND status IN :statuses
        GROUP BY request_id
        """
    ).bindparams(
        bindparam("request_ids", expanding=True),
        bindparam("statuses", expanding=True),
    )
    refund_stmt = text(
        """
        SELECT request_id, COUNT(*) AS cnt
        FROM material_request_refunds
        WHERE request_id IN :request_ids
          AND refund_type = :refund_type
          AND status = :status
        GROUP BY request_id
        """
    ).bindparams(bindparam("request_ids", expanding=True))
    paid_rows = session.execute(
        paid_stmt,
        {"request_ids": request_ids, "statuses": list(paid_contribution_statuses)},
    ).mappings().all()
    refund_rows = session.execute(
        refund_stmt,
        {"request_ids": request_ids, "refund_type": early_exit_refund_type, "status": success_refund_status},
    ).mappings().all()
    paid_counts = {int(row["request_id"]): int(row["cnt"] or 0) for row in paid_rows}
    refund_counts = {int(row["request_id"]): int(row["cnt"] or 0) for row in refund_rows}
    hidden_ids: set[int] = set()
    for request_id in request_ids:
        total_paid = paid_counts.get(request_id, 0)
        early_exit = refund_counts.get(request_id, 0)
        if total_paid > 0 and early_exit >= total_paid:
            hidden_ids.add(request_id)
    return hidden_ids


def compat_exclude_hidden_early_exit_requests(
    session: Session,
    rows: list[dict[str, Any]],
    *,
    paid_contribution_statuses: tuple[str, ...],
    early_exit_refund_type: str,
    success_refund_status: str,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    hidden_ids = compat_load_hidden_early_exit_request_ids(
        session,
        [int(row["id"]) for row in rows],
        paid_contribution_statuses=paid_contribution_statuses,
        early_exit_refund_type=early_exit_refund_type,
        success_refund_status=success_refund_status,
    )
    return [row for row in rows if int(row["id"]) not in hidden_ids]


def compat_request_hidden_by_early_exit(
    session: Session,
    request_id: int,
    *,
    paid_contribution_statuses: tuple[str, ...],
    early_exit_refund_type: str,
    success_refund_status: str,
) -> bool:
    return request_id in compat_load_hidden_early_exit_request_ids(
        session,
        [request_id],
        paid_contribution_statuses=paid_contribution_statuses,
        early_exit_refund_type=early_exit_refund_type,
        success_refund_status=success_refund_status,
    )


def compat_sort_requests(
    rows: list[dict[str, Any]],
    *,
    sort: str | None,
    profile: dict[str, str | None] | None,
) -> list[dict[str, Any]]:
    normalized = (sort or "").lower()
    if profile and any(profile.get(key) for key in ("school", "college", "major")):

        def match_score(row: dict[str, Any]) -> int:
            school = profile.get("school")
            college = profile.get("college")
            major = profile.get("major")
            request_school = row.get("school")
            request_college = row.get("college")
            request_major = row.get("major")
            if not school or not request_school or school != request_school:
                return 0
            if request_college:
                if not college or college != request_college:
                    return 0
                if request_major:
                    if not major or major != request_major:
                        return 0
                    return 3
                return 2
            return 1

        if normalized == "hot":
            return sorted(
                rows,
                key=lambda row: (
                    -match_score(row),
                    -int(row.get("response_count") or 0),
                    -compat_timestamp(row.get("created_at")),
                ),
            )
        return sorted(
            rows,
            key=lambda row: (
                -match_score(row),
                -compat_timestamp(row.get("created_at")),
            ),
        )
    if normalized == "hot":
        return sorted(
            rows,
            key=lambda row: (
                -int(row.get("response_count") or 0),
                -compat_timestamp(row.get("created_at")),
            ),
        )
    return sorted(rows, key=lambda row: -compat_timestamp(row.get("created_at")))


def compat_normalize_list_limit(limit: int | None) -> int | None:
    if limit is None:
        return 6
    if limit <= 0:
        return None
    return clamp_limit(limit, max_value=100)
