from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.services.read_support import ROLE_ADMIN, ROLE_DEVELOPER, clamp_limit, has_role


STATUS_OPEN = "OPEN"
PAID_CONTRIBUTION_STATUSES = ("PAID", "REFUNDING", "REFUNDED")
EARLY_EXIT_REFUND_TYPE = "EARLY_EXIT"
SUCCESS_REFUND_STATUS = "SUCCESS"
LEADERBOARD_MAX_CONTRIBUTION_AMOUNT = 50000


class LegacyRequestsReadService:
    def list_requests(self, session: Session, viewer_id: int | None, *, sort: str | None, limit: int | None) -> list[dict[str, Any]]:
        rows = self._load_open_requests(session)
        visible_rows = self._exclude_hidden_early_exit_requests(session, rows)
        profile = self._load_viewer_profile(session, viewer_id)
        responded_ids = self._load_responded_request_ids(session, viewer_id, [int(row["id"]) for row in visible_rows])
        ordered = self._sort_requests(visible_rows, sort=sort, profile=profile)
        normalized_limit = self._normalize_list_limit(limit)
        if normalized_limit is not None:
            ordered = ordered[:normalized_limit]
        return [self._to_request_item(row, viewer_id, int(row["id"]) in responded_ids) for row in ordered]

    def list_leaderboard(self, session: Session, viewer_id: int | None, *, limit: int | None) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit or 10, 50))
        rows = [
            dict(row)
            for row in session.execute(
                text(
                    """
                    SELECT
                        mr.id,
                        mr.requester_id,
                        mr.course,
                        mr.keyword,
                        mr.school,
                        mr.college,
                        mr.major,
                        mr.budget,
                        mr.funded_amount,
                        mr.contribution_count,
                        mr.deadline,
                        mr.urgency_tier,
                        mr.creator_floor,
                        mr.preview_requirement,
                        mr.anonymous,
                        mr.response_count,
                        mr.accepted_response_id,
                        mr.status,
                        mr.created_at,
                        u.username AS requester_username,
                        u.nickname AS requester_nickname,
                        mr.max_contribution_amount
                    FROM material_requests mr
                    LEFT JOIN users u ON u.id = mr.requester_id
                    WHERE mr.status = 'OPEN'
                      AND mr.funded_amount IS NOT NULL
                      AND mr.funded_amount > 0
                      AND (mr.max_contribution_amount IS NULL OR mr.max_contribution_amount <= :max_amount)
                    ORDER BY mr.funded_amount DESC, mr.created_at DESC
                    LIMIT :limit
                    """
                ),
                {"max_amount": LEADERBOARD_MAX_CONTRIBUTION_AMOUNT, "limit": safe_limit},
            ).mappings().all()
        ]
        visible_rows = self._exclude_hidden_early_exit_requests(session, rows)
        responded_ids = self._load_responded_request_ids(session, viewer_id, [int(row["id"]) for row in visible_rows])
        return [self._to_request_item(row, viewer_id, int(row["id"]) in responded_ids) for row in visible_rows]

    def get_detail(
        self,
        session: Session,
        viewer_id: int,
        viewer_role_mask: int | None,
        request_id: int,
    ) -> dict[str, Any]:
        row = self._load_request_row(session, request_id)
        owner = int(row["requester_id"] or 0) == viewer_id
        can_manage_all = has_role(viewer_role_mask, ROLE_ADMIN) or has_role(viewer_role_mask, ROLE_DEVELOPER)
        if not owner and not can_manage_all and self._request_hidden_by_early_exit(session, request_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="求购不存在")
        if (row["status"] or "").upper() != STATUS_OPEN and not owner and not can_manage_all:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="求购不存在")
        responded = self._request_has_response_from_user(session, request_id, viewer_id)
        return self._to_request_item(row, viewer_id, responded)

    def get_responses(
        self,
        session: Session,
        viewer_id: int,
        viewer_role_mask: int | None,
        request_id: int,
    ) -> list[dict[str, Any]]:
        self._load_request_row(session, request_id)
        rows = session.execute(
            text(
                """
                SELECT
                    rr.id,
                    rr.request_id,
                    rr.responder_id,
                    rr.material_id,
                    rr.message,
                    rr.revision_count,
                    rr.updated_at,
                    rr.created_at,
                    u.username AS responder_username,
                    u.nickname AS responder_nickname
                FROM material_request_responses rr
                LEFT JOIN users u ON u.id = rr.responder_id
                WHERE rr.request_id = :request_id
                ORDER BY rr.created_at DESC
                """
            ),
            {"request_id": request_id},
        ).mappings().all()
        return [
            {
                "id": int(row["id"]),
                "responderName": row["responder_nickname"] or row["responder_username"] or "",
                "message": row["message"],
                "materialId": int(row["material_id"]) if row["material_id"] is not None else None,
                "revisionCount": int(row["revision_count"] or 0),
                "updatedAt": self._serialize_datetime(row["updated_at"]),
                "createdAt": self._serialize_datetime(row["created_at"]),
            }
            for row in rows
        ]

    def get_contributions(
        self,
        session: Session,
        viewer_id: int,
        viewer_role_mask: int | None,
        request_id: int,
    ) -> list[dict[str, Any]]:
        self._load_request_row(session, request_id)
        rows = session.execute(
            text(
                """
                SELECT
                    c.id,
                    c.contributor_id,
                    c.type,
                    c.amount,
                    c.status,
                    c.deadline_tier,
                    c.deadline_at,
                    c.created_at,
                    u.username AS contributor_username,
                    u.nickname AS contributor_nickname
                FROM material_request_contributions c
                LEFT JOIN users u ON u.id = c.contributor_id
                WHERE c.request_id = :request_id
                  AND c.status = 'PAID'
                ORDER BY c.created_at DESC
                """
            ),
            {"request_id": request_id},
        ).mappings().all()
        return [
            {
                "id": int(row["id"]),
                "contributorId": int(row["contributor_id"]) if row["contributor_id"] is not None else None,
                "contributorName": row["contributor_nickname"] or row["contributor_username"] or "用户",
                "type": row["type"],
                "amount": self._to_amount_yuan(row["amount"]),
                "status": row["status"],
                "deadlineTier": row["deadline_tier"],
                "deadlineAt": self._serialize_datetime(row["deadline_at"]),
                "createdAt": self._serialize_datetime(row["created_at"]),
            }
            for row in rows
        ]

    def _load_open_requests(self, session: Session) -> list[dict[str, Any]]:
        rows = session.execute(
            text(
                """
                SELECT
                    mr.id,
                    mr.requester_id,
                    mr.course,
                    mr.keyword,
                    mr.school,
                    mr.college,
                    mr.major,
                    mr.budget,
                    mr.funded_amount,
                    mr.contribution_count,
                    mr.deadline,
                    mr.urgency_tier,
                    mr.creator_floor,
                    mr.preview_requirement,
                    mr.anonymous,
                    mr.response_count,
                    mr.accepted_response_id,
                    mr.status,
                    mr.created_at,
                    u.username AS requester_username,
                    u.nickname AS requester_nickname
                FROM material_requests mr
                LEFT JOIN users u ON u.id = mr.requester_id
                WHERE mr.status = 'OPEN'
                """
            )
        ).mappings().all()
        return [dict(row) for row in rows]

    def _load_request_row(self, session: Session, request_id: int) -> dict[str, Any]:
        row = session.execute(
            text(
                """
                SELECT
                    mr.id,
                    mr.requester_id,
                    mr.course,
                    mr.keyword,
                    mr.school,
                    mr.college,
                    mr.major,
                    mr.budget,
                    mr.funded_amount,
                    mr.contribution_count,
                    mr.deadline,
                    mr.urgency_tier,
                    mr.creator_floor,
                    mr.preview_requirement,
                    mr.anonymous,
                    mr.response_count,
                    mr.accepted_response_id,
                    mr.status,
                    mr.created_at,
                    u.username AS requester_username,
                    u.nickname AS requester_nickname
                FROM material_requests mr
                LEFT JOIN users u ON u.id = mr.requester_id
                WHERE mr.id = :request_id
                LIMIT 1
                """
            ),
            {"request_id": request_id},
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="求购不存在")
        return dict(row)

    def _exclude_hidden_early_exit_requests(self, session: Session, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not rows:
            return []
        hidden_ids = self._load_hidden_early_exit_request_ids(session, [int(row["id"]) for row in rows])
        return [row for row in rows if int(row["id"]) not in hidden_ids]

    def _request_hidden_by_early_exit(self, session: Session, request_id: int) -> bool:
        return request_id in self._load_hidden_early_exit_request_ids(session, [request_id])

    def _load_hidden_early_exit_request_ids(self, session: Session, request_ids: list[int]) -> set[int]:
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
            {"request_ids": request_ids, "statuses": list(PAID_CONTRIBUTION_STATUSES)},
        ).mappings().all()
        refund_rows = session.execute(
            refund_stmt,
            {"request_ids": request_ids, "refund_type": EARLY_EXIT_REFUND_TYPE, "status": SUCCESS_REFUND_STATUS},
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

    def _load_viewer_profile(self, session: Session, viewer_id: int | None) -> dict[str, str | None] | None:
        if viewer_id is None:
            return None
        row = session.execute(
            text(
                """
                SELECT school, college, major
                FROM users
                WHERE id = :viewer_id
                LIMIT 1
                """
            ),
            {"viewer_id": viewer_id},
        ).mappings().first()
        if row is None:
            return None
        return {"school": row["school"], "college": row["college"], "major": row["major"]}

    def _load_responded_request_ids(self, session: Session, viewer_id: int | None, request_ids: list[int]) -> set[int]:
        if viewer_id is None or not request_ids:
            return set()
        stmt = text(
            """
            SELECT request_id
            FROM material_request_responses
            WHERE responder_id = :viewer_id
              AND request_id IN :request_ids
            """
        ).bindparams(bindparam("request_ids", expanding=True))
        rows = session.execute(stmt, {"viewer_id": viewer_id, "request_ids": request_ids}).scalars().all()
        return {int(value) for value in rows}

    def _request_has_response_from_user(self, session: Session, request_id: int, viewer_id: int | None) -> bool:
        if viewer_id is None:
            return False
        exists = session.execute(
            text(
                """
                SELECT 1
                FROM material_request_responses
                WHERE request_id = :request_id
                  AND responder_id = :viewer_id
                LIMIT 1
                """
            ),
            {"request_id": request_id, "viewer_id": viewer_id},
        ).scalar()
        return exists is not None

    def _sort_requests(
        self,
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
                        -self._timestamp(row.get("created_at")),
                    ),
                )
            return sorted(
                rows,
                key=lambda row: (
                    -match_score(row),
                    -self._timestamp(row.get("created_at")),
                ),
            )
        if normalized == "hot":
            return sorted(
                rows,
                key=lambda row: (
                    -int(row.get("response_count") or 0),
                    -self._timestamp(row.get("created_at")),
                ),
            )
        return sorted(rows, key=lambda row: -self._timestamp(row.get("created_at")))

    def _timestamp(self, value: Any) -> float:
        serialized = self._serialize_datetime(value)
        if not serialized:
            return 0.0
        normalized = serialized.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).timestamp()

    def _normalize_list_limit(self, limit: int | None) -> int | None:
        if limit is None:
            return 6
        if limit <= 0:
            return None
        return clamp_limit(limit, max_value=100)

    def _to_request_item(self, row: dict[str, Any], viewer_id: int | None, responded: bool) -> dict[str, Any]:
        requester_id = int(row["requester_id"]) if row["requester_id"] is not None else None
        owner = viewer_id is not None and requester_id == viewer_id
        anonymous = bool(row["anonymous"])
        requester_name = row["requester_nickname"] or row["requester_username"] or ""
        if anonymous and not owner:
            requester_name = "匿名同学"
        return {
            "id": int(row["id"]),
            "course": row["course"],
            "keyword": row["keyword"],
            "school": row["school"],
            "college": row["college"],
            "major": row["major"],
            "budget": self._to_amount_yuan(row["budget"]),
            "fundedAmount": self._to_amount_yuan(row["funded_amount"]),
            "contributionCount": int(row["contribution_count"] or 0),
            "deadline": row["deadline"],
            "urgencyTier": row["urgency_tier"],
            "creatorFloor": self._to_amount_yuan(row["creator_floor"]),
            "previewRequirement": row["preview_requirement"],
            "anonymous": anonymous,
            "requesterName": requester_name,
            "responseCount": int(row["response_count"] or 0),
            "responded": responded,
            "owner": owner,
            "acceptedResponseId": int(row["accepted_response_id"]) if row["accepted_response_id"] is not None else None,
            "status": row["status"],
            "createdAt": self._serialize_datetime(row["created_at"]),
        }

    def _to_amount_yuan(self, cents: Any) -> float | None:
        if cents is None:
            return None
        return round(int(cents) / 100.0, 2)

    def _serialize_datetime(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            else:
                value = value.astimezone(UTC)
            return value.isoformat().replace("+00:00", "Z")
        return str(value)
