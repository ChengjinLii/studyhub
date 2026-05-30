from __future__ import annotations

from datetime import date, datetime
import uuid
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.requests import (
    RequestArbitrationRecord,
    RequestContributionRecord,
    RequestPreviewViewRecord,
    RequestRecord,
    RequestResponseRecord,
)


class RequestRepository:
    def ensure_seed_bootstrap(self, session: Session, seed: dict[str, Any]) -> None:
        if not seed:
            return
        items = seed.get("requests") or []
        seed_count = int(session.scalar(select(func.count()).select_from(RequestRecord).where(RequestRecord.source == "seed")) or 0)
        if seed_count >= len(items) and seed_count > 0:
            return

        responses_map = seed.get("requestResponses") or {}
        contributions_map = seed.get("requestContributions") or {}

        for item in items:
            request_id = int(item["id"])
            entity = session.get(RequestRecord, request_id)
            if entity is None:
                entity = RequestRecord(
                    id=request_id,
                    source="seed",
                    requester_id=int(item["requesterId"]) if item.get("requesterId") is not None else None,
                    requester_name=item.get("requesterName"),
                    course=item.get("course"),
                    keyword=item.get("keyword"),
                    school=item.get("school"),
                    college=item.get("college"),
                    major=item.get("major"),
                    budget_cents=self._to_cents(item.get("budget")),
                    funded_amount_cents=self._to_cents(item.get("fundedAmount")),
                    contribution_count=int(item.get("contributionCount", 0) or 0),
                    response_count=int(item.get("responseCount", 0) or 0),
                    deadline=self._parse_date(item.get("deadline")),
                    urgency_tier=item.get("urgencyTier"),
                    creator_floor_cents=self._to_cents(item.get("creatorFloor")),
                    preview_requirement=item.get("previewRequirement"),
                    anonymous=bool(item.get("anonymous")),
                    accepted_response_id=int(item["acceptedResponseId"]) if item.get("acceptedResponseId") is not None else None,
                    status=item.get("status") or "OPEN",
                    created_at=self._parse_datetime(item.get("createdAt")),
                    updated_at=self._parse_datetime(item.get("createdAt")),
                )
                session.add(entity)

            for response_item in responses_map.get(str(request_id), []):
                response_id = int(response_item["id"])
                response_entity = session.get(RequestResponseRecord, response_id)
                if response_entity is None:
                    response_entity = RequestResponseRecord(
                        id=response_id,
                        source="seed",
                        request_id=request_id,
                        responder_id=self._resolve_user_id(seed, response_item.get("responderName")),
                        responder_name=response_item.get("responderName"),
                        message=response_item.get("message"),
                        material_id=int(response_item["materialId"]) if response_item.get("materialId") is not None else None,
                        revision_count=int(response_item.get("revisionCount", 0) or 0),
                        created_at=self._parse_datetime(response_item.get("createdAt")) or entity.created_at,
                        updated_at=self._parse_datetime(response_item.get("updatedAt")) or entity.updated_at,
                    )
                    session.add(response_entity)

            for contribution_item in contributions_map.get(str(request_id), []):
                contribution_id = int(contribution_item["id"])
                contribution_entity = session.get(RequestContributionRecord, contribution_id)
                if contribution_entity is None:
                    contribution_entity = RequestContributionRecord(
                        id=contribution_id,
                        source="seed",
                        request_id=request_id,
                        contributor_id=int(contribution_item["contributorId"]) if contribution_item.get("contributorId") is not None else None,
                        contributor_name=contribution_item.get("contributorName"),
                        type=contribution_item.get("type") or "FOLLOWER",
                        amount_cents=self._to_cents(contribution_item.get("amount")) or 0,
                        status=contribution_item.get("status") or "PAID",
                        deadline_tier=contribution_item.get("deadlineTier"),
                        deadline_at=self._parse_datetime(contribution_item.get("deadlineAt")),
                        out_trade_no=f"RQSEED{contribution_id}",
                        paid_at=self._parse_datetime(contribution_item.get("createdAt")),
                        created_at=self._parse_datetime(contribution_item.get("createdAt")) or entity.created_at,
                        updated_at=self._parse_datetime(contribution_item.get("createdAt")) or entity.updated_at,
                    )
                    session.add(contribution_entity)

        session.flush()

    def list_requests(self, session: Session) -> list[RequestRecord]:
        stmt = select(RequestRecord).order_by(RequestRecord.created_at.desc(), RequestRecord.id.desc())
        return list(session.scalars(stmt))

    def list_public_requests(self, session: Session, *, sort: str | None, limit: int | None = None) -> list[RequestRecord]:
        stmt = select(RequestRecord).where(RequestRecord.status == "OPEN")
        stmt = self._order_public_requests(stmt, sort)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(session.scalars(stmt))

    def list_visible_public_requests(self, session: Session, *, sort: str | None, limit: int | None = None) -> list[RequestRecord]:
        hidden_ids = (
            select(RequestContributionRecord.request_id)
            .where(RequestContributionRecord.status.in_(("PAID", "REFUNDING", "REFUNDED")))
            .group_by(RequestContributionRecord.request_id)
            .having(
                func.sum(case((RequestContributionRecord.status == "REFUNDED", 1), else_=0)) == func.count()
            )
        )
        stmt = select(RequestRecord).where(RequestRecord.status == "OPEN", RequestRecord.id.not_in(hidden_ids))
        stmt = self._order_public_requests(stmt, sort)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(session.scalars(stmt))

    def _order_public_requests(self, stmt, sort: str | None):
        normalized = (sort or "latest").lower()
        if normalized == "hot":
            return stmt.order_by(
                RequestRecord.funded_amount_cents.desc(),
                RequestRecord.response_count.desc(),
                RequestRecord.created_at.desc(),
                RequestRecord.id.desc(),
            )
        return stmt.order_by(RequestRecord.created_at.desc(), RequestRecord.id.desc())

    def find_hidden_early_exit_request_ids(self, session: Session, *, request_ids: list[int]) -> set[int]:
        if not request_ids:
            return set()
        stmt = (
            select(RequestContributionRecord.request_id)
            .where(
                RequestContributionRecord.request_id.in_(sorted(set(request_ids))),
                RequestContributionRecord.status.in_(("PAID", "REFUNDING", "REFUNDED")),
            )
            .group_by(RequestContributionRecord.request_id)
            .having(
                func.sum(case((RequestContributionRecord.status == "REFUNDED", 1), else_=0)) == func.count()
            )
        )
        return {int(value) for value in session.scalars(stmt)}

    def find_responded_request_ids(self, session: Session, *, responder_id: int | None, request_ids: list[int]) -> set[int]:
        if responder_id is None or not request_ids:
            return set()
        stmt = select(RequestResponseRecord.request_id).where(
            RequestResponseRecord.responder_id == responder_id,
            RequestResponseRecord.request_id.in_(sorted(set(request_ids))),
        )
        return {int(value) for value in session.scalars(stmt)}

    def get_request(self, session: Session, request_id: int) -> RequestRecord | None:
        return session.get(RequestRecord, request_id)

    def next_request_id(self, session: Session, seed: dict[str, Any]) -> int:
        seed_max = max((int(item["id"]) for item in seed.get("requests") or []), default=0)
        db_max = int(session.scalar(select(func.max(RequestRecord.id))) or 0)
        return max(seed_max, db_max) + 1

    def save_request(self, session: Session, entity: RequestRecord) -> RequestRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def list_responses(self, session: Session, request_id: int) -> list[RequestResponseRecord]:
        stmt = select(RequestResponseRecord).where(RequestResponseRecord.request_id == request_id).order_by(RequestResponseRecord.created_at.desc(), RequestResponseRecord.id.desc())
        return list(session.scalars(stmt))

    def get_response(self, session: Session, response_id: int) -> RequestResponseRecord | None:
        return session.get(RequestResponseRecord, response_id)

    def find_response_by_request_and_responder(self, session: Session, request_id: int, responder_id: int) -> RequestResponseRecord | None:
        stmt = select(RequestResponseRecord).where(RequestResponseRecord.request_id == request_id, RequestResponseRecord.responder_id == responder_id)
        return session.scalar(stmt)

    def save_response(self, session: Session, entity: RequestResponseRecord) -> RequestResponseRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def next_response_id(self, session: Session, seed: dict[str, Any]) -> int:
        seed_max = max(
            (int(item["id"]) for items in (seed.get("requestResponses") or {}).values() for item in items),
            default=0,
        )
        db_max = int(session.scalar(select(func.max(RequestResponseRecord.id))) or 0)
        return max(seed_max, db_max) + 1

    def list_contributions(self, session: Session, request_id: int) -> list[RequestContributionRecord]:
        stmt = select(RequestContributionRecord).where(RequestContributionRecord.request_id == request_id).order_by(RequestContributionRecord.created_at.desc(), RequestContributionRecord.id.desc())
        return list(session.scalars(stmt))

    def list_paid_like_contributions(self, session: Session, request_id: int) -> list[RequestContributionRecord]:
        stmt = (
            select(RequestContributionRecord)
            .where(
                RequestContributionRecord.request_id == request_id,
                RequestContributionRecord.status.in_(("PAID", "REFUNDING", "REFUNDED")),
            )
            .order_by(RequestContributionRecord.created_at.desc(), RequestContributionRecord.id.desc())
        )
        return list(session.scalars(stmt))

    def get_contribution(self, session: Session, contribution_id: int) -> RequestContributionRecord | None:
        return session.get(RequestContributionRecord, contribution_id)

    def find_contribution_by_out_trade_no(self, session: Session, out_trade_no: str) -> RequestContributionRecord | None:
        stmt = select(RequestContributionRecord).where(RequestContributionRecord.out_trade_no == out_trade_no)
        return session.scalar(stmt)

    def save_contribution(self, session: Session, entity: RequestContributionRecord) -> RequestContributionRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def next_contribution_id(self, session: Session, seed: dict[str, Any]) -> int:
        seed_max = max(
            (int(item["id"]) for items in (seed.get("requestContributions") or {}).values() for item in items),
            default=0,
        )
        db_max = int(session.scalar(select(func.max(RequestContributionRecord.id))) or 0)
        return max(seed_max, db_max) + 1

    def build_out_trade_no(self) -> str:
        return "RQ" + uuid.uuid4().hex[:24].upper()

    def find_preview_view(self, session: Session, request_id: int, response_id: int, viewer_id: int) -> RequestPreviewViewRecord | None:
        stmt = select(RequestPreviewViewRecord).where(
            RequestPreviewViewRecord.request_id == request_id,
            RequestPreviewViewRecord.response_id == response_id,
            RequestPreviewViewRecord.viewer_id == viewer_id,
        )
        return session.scalar(stmt)

    def save_preview_view(self, session: Session, entity: RequestPreviewViewRecord) -> RequestPreviewViewRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def has_preview_view(self, session: Session, request_id: int, response_id: int, viewer_id: int, *, min_loaded_count: int) -> bool:
        stmt = select(RequestPreviewViewRecord.id).where(
            RequestPreviewViewRecord.request_id == request_id,
            RequestPreviewViewRecord.response_id == response_id,
            RequestPreviewViewRecord.viewer_id == viewer_id,
            RequestPreviewViewRecord.loaded_count >= min_loaded_count,
        )
        return session.scalar(stmt) is not None

    def list_arbitrations(self, session: Session, request_id: int | None = None) -> list[RequestArbitrationRecord]:
        stmt = select(RequestArbitrationRecord)
        if request_id is not None:
            stmt = stmt.where(RequestArbitrationRecord.request_id == request_id)
        stmt = stmt.order_by(RequestArbitrationRecord.created_at.desc(), RequestArbitrationRecord.id.desc())
        return list(session.scalars(stmt))

    def get_arbitration(self, session: Session, arbitration_id: int) -> RequestArbitrationRecord | None:
        return session.get(RequestArbitrationRecord, arbitration_id)

    def find_pending_arbitration(self, session: Session, request_id: int) -> RequestArbitrationRecord | None:
        stmt = select(RequestArbitrationRecord).where(
            RequestArbitrationRecord.request_id == request_id,
            RequestArbitrationRecord.status == "PENDING",
        )
        return session.scalar(stmt)

    def list_timed_out_pending_arbitrations(self, session: Session, threshold: datetime) -> list[RequestArbitrationRecord]:
        stmt = select(RequestArbitrationRecord).where(
            RequestArbitrationRecord.status == "PENDING",
            RequestArbitrationRecord.created_at <= threshold,
        )
        return list(session.scalars(stmt))

    def list_timed_out_unanswered_requests(self, session: Session, *, created_before: datetime) -> list[RequestRecord]:
        stmt = (
            select(RequestRecord)
            .where(
                RequestRecord.source != "seed",
                RequestRecord.accepted_response_id.is_(None),
                RequestRecord.status.in_(("OPEN", "REFUNDING")),
                RequestRecord.response_count == 0,
                RequestRecord.created_at <= created_before,
            )
            .order_by(RequestRecord.created_at.asc(), RequestRecord.id.asc())
        )
        return list(session.scalars(stmt))

    def list_requests_with_expired_delivery_window(
        self,
        session: Session,
        *,
        latest_deadline_before: datetime,
    ) -> list[RequestRecord]:
        deadline_subquery = (
            select(
                RequestContributionRecord.request_id.label("request_id"),
                func.max(RequestContributionRecord.deadline_at).label("latest_deadline"),
            )
            .where(
                RequestContributionRecord.status == "PAID",
                RequestContributionRecord.deadline_at.is_not(None),
            )
            .group_by(RequestContributionRecord.request_id)
            .subquery()
        )
        stmt = (
            select(RequestRecord)
            .join(deadline_subquery, deadline_subquery.c.request_id == RequestRecord.id)
            .where(
                RequestRecord.source != "seed",
                RequestRecord.accepted_response_id.is_(None),
                RequestRecord.status.in_(("OPEN", "REFUNDING")),
                deadline_subquery.c.latest_deadline <= latest_deadline_before,
            )
            .order_by(deadline_subquery.c.latest_deadline.asc(), RequestRecord.id.asc())
        )
        return list(session.scalars(stmt))

    def save_arbitration(self, session: Session, entity: RequestArbitrationRecord) -> RequestArbitrationRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def next_arbitration_id(self, session: Session) -> int:
        db_max = int(session.scalar(select(func.max(RequestArbitrationRecord.id))) or 0)
        return db_max + 1

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def _parse_date(self, value: str | None) -> date | None:
        if not value:
            return None
        return date.fromisoformat(value)

    def _to_cents(self, value: Any) -> int | None:
        if value is None:
            return None
        return int(round(float(value) * 100))

    def _resolve_user_id(self, seed: dict[str, Any], responder_name: str | None) -> int | None:
        if not responder_name:
            return None
        for raw_id, snapshot in (seed.get("users") or {}).items():
            if responder_name in {snapshot.get("nickname"), snapshot.get("username")}:
                return int(raw_id)
        return None
