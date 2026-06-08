from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.async_db import async_session_scope
from app.core.config import Settings
from app.models.materials import MaterialRecord
from app.models.requests import (
    RequestArbitrationRecord,
    RequestContributionRecord,
    RequestPreviewViewRecord,
    RequestRecord,
    RequestResponseRecord,
)
from app.repos.auth_repo import AuthRepository
from app.repos.material_repo import MaterialRepository
from app.repos.read_api_repo import ReadApiRepository
from app.repos.request_repo import RequestRepository
from app.schemas.requests import (
    RequestAcceptPayload,
    RequestArbitrationDecisionPayload,
    RequestContributionCreatePayload,
    RequestContributionDeadlinePayload,
    RequestCreatePayload,
    RequestDisputePayload,
    RequestPreviewViewPayload,
    RequestRespondPayload,
)
from app.services.requests_query_support import (
    compat_exclude_hidden_early_exit_requests,
    compat_load_hidden_early_exit_request_ids,
    compat_normalize_list_limit,
    compat_request_hidden_by_early_exit,
    compat_sort_requests,
)
from app.services.requests_compat import RequestsCompatMixin
from app.services.requests_serializers import amount_to_yuan, request_contribution_item, request_response_item
from app.services.read_support import (
    ROLE_ADMIN,
    ROLE_DEVELOPER,
    clamp_limit,
    compat_amount_yuan,
    compat_serialize_datetime,
    has_role,
    parse_iso_datetime,
    serialize_datetime,
)


REQUEST_STATUS_OPEN = "OPEN"
REQUEST_STATUS_CLOSED = "CLOSED"
REQUEST_STATUS_PENDING_PAYMENT = "PENDING_PAYMENT"
REQUEST_STATUS_FULFILLED = "FULFILLED"
REQUEST_STATUS_REFUNDING = "REFUNDING"
REQUEST_STATUS_REFUNDED = "REFUNDED"
REQUEST_STATUS_DISPUTED = "DISPUTED"
REQUEST_STATUS_REVISION_REQUIRED = "REVISION_REQUIRED"

CONTRIBUTION_STATUS_CREATED = "CREATED"
CONTRIBUTION_STATUS_PAID = "PAID"
CONTRIBUTION_STATUS_REFUNDING = "REFUNDING"
CONTRIBUTION_STATUS_REFUNDED = "REFUNDED"

ARBITRATION_STATUS_PENDING = "PENDING"
ARBITRATION_STATUS_APPROVED = "APPROVED"
ARBITRATION_STATUS_REVISION = "REVISION"
ARBITRATION_STATUS_REFUNDING = "REFUNDING"
ARBITRATION_STATUS_REFUNDED = "REFUNDED"

TYPE_OWNER = "OWNER"
TYPE_FOLLOWER = "FOLLOWER"
CONTRIBUTION_VISIBLE_STATUSES = {CONTRIBUTION_STATUS_PAID, CONTRIBUTION_STATUS_REFUNDING, CONTRIBUTION_STATUS_REFUNDED}
OWNER_MINIMUMS = {"24H": 5000, "WEEK": 2000, "MONTH": 1000, "FLEX": 500}
FOLLOWER_MINIMUMS = {"24H": 3000, "WEEK": 1500, "MONTH": 1000, "FLEX": 500}
NO_ACCEPT_HOURS = 48
NO_DELIVERY_DAYS = 45
ARBITRATION_TIMEOUT_HOURS = 24
LEADERBOARD_MAX_CONTRIBUTION_AMOUNT = 50000
COMPAT_PAID_CONTRIBUTION_STATUSES = ("PAID", "REFUNDING", "REFUNDED")
EARLY_EXIT_REFUND_TYPE = "EARLY_EXIT"
SUCCESS_REFUND_STATUS = "SUCCESS"


class RequestsService(RequestsCompatMixin):
    """Step 10 先把求购状态机、仲裁和本地支付占位语义落到仓库内，不依赖旧 Java 服务。"""

    def __init__(
        self,
        settings: Settings,
        read_repo: ReadApiRepository,
        auth_repo: AuthRepository,
        material_repo: MaterialRepository,
        request_repo: RequestRepository,
    ) -> None:
        self.settings = settings
        self.read_repo = read_repo
        self.auth_repo = auth_repo
        self.material_repo = material_repo
        self.request_repo = request_repo

    def list_requests(self, session: Session, viewer_id: int | None, *, sort: str | None, limit: int | None) -> list[dict[str, Any]]:
        if self.settings.requires_private_env_file:
            return self._compat_list_requests(session, viewer_id, sort=sort, limit=limit)
        self._bootstrap(session)
        normalized = (sort or "latest").lower()
        safe_limit = clamp_limit(limit, max_value=100)
        sliced = self.request_repo.list_visible_public_requests(session, sort=normalized, limit=safe_limit)
        responded_ids = self.request_repo.find_responded_request_ids(
            session,
            responder_id=viewer_id,
            request_ids=[int(item.id) for item in sliced],
        )
        return [
            self._to_request_item(session, item, viewer_id, None, responded_ids=responded_ids)
            for item in sliced
        ]

    async def list_requests_async(self, session: Session, viewer_id: int | None, *, sort: str | None, limit: int | None) -> list[dict[str, Any]]:
        if not (self.settings.requires_private_env_file and self.settings.async_read_db_enabled):
            return await asyncio.to_thread(self.list_requests, session, viewer_id, sort=sort, limit=limit)

        rows, profile = await asyncio.gather(
            self._call_with_new_async_session(self._compat_load_open_requests_async),
            self._call_with_new_async_session(self._compat_load_viewer_profile_async, viewer_id),
        )
        visible_rows = await self._compat_exclude_hidden_early_exit_requests_async(rows)
        responded_ids = await self._call_with_new_async_session(
            self._compat_load_responded_request_ids_async,
            viewer_id,
            [int(row["id"]) for row in visible_rows],
        )
        ordered = self._compat_sort_requests(visible_rows, sort=sort, profile=profile)
        normalized_limit = self._compat_normalize_list_limit(limit)
        if normalized_limit is not None:
            ordered = ordered[:normalized_limit]
        return [self._compat_to_request_item(row, viewer_id, int(row["id"]) in responded_ids) for row in ordered]

    def list_leaderboard(self, session: Session, viewer_id: int | None, *, limit: int | None) -> list[dict[str, Any]]:
        if self.settings.requires_private_env_file:
            return self._compat_list_leaderboard(session, viewer_id, limit=limit)
        return self.list_requests(session, viewer_id, sort="hot", limit=limit or 10)

    async def list_leaderboard_async(self, session: Session, viewer_id: int | None, *, limit: int | None) -> list[dict[str, Any]]:
        if not (self.settings.requires_private_env_file and self.settings.async_read_db_enabled):
            return await asyncio.to_thread(self.list_leaderboard, session, viewer_id, limit=limit)

        safe_limit = max(1, min(limit or 10, 50))
        rows = await self._call_with_new_async_session(self._compat_load_leaderboard_rows_async, safe_limit)
        visible_rows = await self._compat_exclude_hidden_early_exit_requests_async(rows)
        responded_ids = await self._call_with_new_async_session(
            self._compat_load_responded_request_ids_async,
            viewer_id,
            [int(row["id"]) for row in visible_rows],
        )
        return [self._compat_to_request_item(row, viewer_id, int(row["id"]) in responded_ids) for row in visible_rows]

    def get_detail(self, session: Session, viewer_id: int, viewer_role_mask: int | None, request_id: int) -> dict[str, Any]:
        if self.settings.requires_private_env_file:
            return self._compat_get_detail(session, viewer_id, viewer_role_mask, request_id)
        self._bootstrap(session)
        request = self._require_request(session, request_id)
        is_owner = request.requester_id == viewer_id
        can_manage_all = self._can_manage_all(viewer_role_mask)
        if not is_owner and not can_manage_all and (not self._is_publicly_visible(request) or self._should_hide_by_early_exit(session, request)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="求购不存在")
        return self._to_request_item(session, request, viewer_id, viewer_role_mask)

    def get_responses(self, session: Session, viewer_id: int, viewer_role_mask: int | None, request_id: int) -> list[dict[str, Any]]:
        if self.settings.requires_private_env_file:
            return self._compat_get_responses(session, viewer_id, viewer_role_mask, request_id)
        self._bootstrap(session)
        request = self._require_request_with_access(session, request_id, viewer_id, viewer_role_mask)
        _ = request
        items = self.request_repo.list_responses(session, request_id)
        items.sort(key=lambda item: -parse_iso_datetime(serialize_datetime(item.updated_at) or serialize_datetime(item.created_at)).timestamp())
        return [request_response_item(item) for item in items]

    def get_contributions(self, session: Session, viewer_id: int, viewer_role_mask: int | None, request_id: int) -> list[dict[str, Any]]:
        if self.settings.requires_private_env_file:
            return self._compat_get_contributions(session, viewer_id, viewer_role_mask, request_id)
        self._bootstrap(session)
        request = self._require_request_with_access(session, request_id, viewer_id, viewer_role_mask)
        _ = request
        items = [item for item in self.request_repo.list_contributions(session, request_id) if item.status in CONTRIBUTION_VISIBLE_STATUSES]
        items.sort(key=lambda item: -self._created_ts(item))
        return [request_contribution_item(item) for item in items]

    async def _call_with_new_async_session(self, loader, *args, **kwargs):
        async with async_session_scope() as session:
            return await loader(session, *args, **kwargs)

    async def _compat_exclude_hidden_early_exit_requests_async(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not rows:
            return []
        hidden_ids = await self._call_with_new_async_session(
            self._compat_load_hidden_early_exit_request_ids_async,
            [int(row["id"]) for row in rows],
        )
        return [row for row in rows if int(row["id"]) not in hidden_ids]

    def create_request(self, session: Session, user_id: int, payload: RequestCreatePayload) -> dict[str, Any]:
        seed = self._bootstrap(session)
        requester = self._require_user(session, user_id)
        course = self._strip(payload.course)
        keyword = self._strip(payload.keyword)
        if not course and not keyword:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请填写标题或简介")
        school = self._strip(payload.school)
        college = self._strip(payload.college)
        major = self._strip(payload.major)
        if not school and (college or major):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请选择学校")
        if not college and major:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请选择学院")
        budget = self._normalize_money(payload.budget)
        urgency_tier = self._normalize_tier(payload.urgencyTier, "FLEX")
        if budget is not None and budget < OWNER_MINIMUMS[urgency_tier]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="求购金额不足当前期限档位最低要求")
        creator_floor = self._normalize_money(payload.creatorFloor)
        if creator_floor is not None:
            if budget is None or budget <= 0:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="设置跟购底价需先填写预算")
            max_floor = max(500, int(budget * 0.6))
            if creator_floor < 500:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="跟购底价最低 5 元")
            if creator_floor > max_floor:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="跟购底价超出可设置范围")
        now = datetime.now(UTC)
        entity = RequestRecord(
            id=self.request_repo.next_request_id(session, seed),
            source="local",
            requester_id=requester.id,
            requester_name=requester.nickname or requester.username,
            course=course,
            keyword=keyword,
            school=school,
            college=college,
            major=major,
            budget_cents=budget,
            funded_amount_cents=0,
            contribution_count=0,
            response_count=0,
            max_contribution_amount_cents=0,
            deadline=self._compute_deadline_date(now, urgency_tier),
            urgency_tier=urgency_tier,
            creator_floor_cents=creator_floor,
            preview_requirement=self._strip(payload.previewRequirement),
            anonymous=bool(payload.anonymous),
            status=REQUEST_STATUS_PENDING_PAYMENT if budget and budget > 0 else REQUEST_STATUS_OPEN,
            created_at=now,
            updated_at=now,
        )
        self.request_repo.save_request(session, entity)
        result: dict[str, Any] = {
            "request": self._to_request_item(session, entity, user_id, requester.role_mask),
            "paymentRequired": False,
        }
        if budget and budget > 0:
            contribution = self._create_contribution(
                session,
                request=entity,
                contributor_id=requester.id,
                contributor_name=requester.nickname or requester.username,
                amount_cents=budget,
                contribution_type=TYPE_OWNER,
                deadline_tier=urgency_tier,
                status_value=CONTRIBUTION_STATUS_CREATED,
                seed=seed,
            )
            result.update(
                {
                    "paymentRequired": True,
                    "contributionId": contribution.id,
                    "outTradeNo": contribution.out_trade_no,
                    "form": self._build_local_pay_form(contribution.out_trade_no or ""),
                }
            )
        session.commit()
        return result

    def follow_request(self, session: Session, request_id: int, user_id: int, payload: RequestContributionCreatePayload) -> dict[str, Any]:
        seed = self._bootstrap(session)
        self._process_timeouts(session)
        request = self._require_request(session, request_id)
        if request.status != REQUEST_STATUS_OPEN:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="求购暂不可跟购")
        if request.requester_id == user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能跟购自己的求购")
        contributor = self._require_user(session, user_id)
        tier = self._normalize_tier(payload.deadlineTier, request.urgency_tier)
        min_amount = max(FOLLOWER_MINIMUMS[tier], int(request.creator_floor_cents or 0))
        if payload.amount < min_amount:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="跟购金额不足最低要求")
        contribution = self._create_contribution(
            session,
            request=request,
            contributor_id=contributor.id,
            contributor_name=contributor.nickname or contributor.username,
            amount_cents=payload.amount,
            contribution_type=TYPE_FOLLOWER,
            deadline_tier=tier,
            status_value=CONTRIBUTION_STATUS_CREATED,
            seed=seed,
        )
        session.commit()
        return {
            "contributionId": contribution.id,
            "outTradeNo": contribution.out_trade_no,
            "form": self._build_local_pay_form(contribution.out_trade_no or ""),
        }

    def get_contribution_status(self, session: Session, out_trade_no: str, user_id: int, *, force_check: bool) -> dict[str, Any]:
        self._bootstrap(session)
        contribution = self.request_repo.find_contribution_by_out_trade_no(session, out_trade_no)
        if contribution is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="跟购记录不存在")
        if contribution.contributor_id is not None and contribution.contributor_id != user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看该记录")
        if force_check and contribution.status == CONTRIBUTION_STATUS_CREATED:
            self._mark_contribution_paid(session, contribution)
            session.commit()
        return {
            "status": contribution.status,
            "requestId": contribution.request_id,
            "contributionId": contribution.id,
        }

    def respond(self, session: Session, request_id: int, user_id: int, payload: RequestRespondPayload) -> dict[str, Any]:
        self._bootstrap(session)
        response = self._upsert_response(
            session,
            request_id=request_id,
            user_id=user_id,
            material_id=payload.materialId,
            message=self._strip(payload.message),
        )
        session.commit()
        return request_response_item(response)

    def attach_material_to_request(self, session: Session, request_id: int, user_id: int, material_id: int) -> None:
        self._bootstrap(session)
        self._upsert_response(session, request_id=request_id, user_id=user_id, material_id=material_id, message=None)
        session.commit()

    def accept_response(self, session: Session, request_id: int, user_id: int, viewer_role_mask: int | None, payload: RequestAcceptPayload) -> dict[str, Any]:
        self._bootstrap(session)
        self._process_timeouts(session)
        request = self._require_request(session, request_id)
        owner = request.requester_id == user_id
        can_manage_all = self._can_manage_all(viewer_role_mask)
        if not owner and not can_manage_all:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作该求购")
        if request.status != REQUEST_STATUS_OPEN:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前求购不可采纳")
        if request.accepted_response_id is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该求购已采纳")
        response = self._require_response_for_request(session, request_id, payload.responseId)
        if response.material_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="应答需关联资料")
        if owner and not can_manage_all and not self.request_repo.has_preview_view(session, request_id, response.id, user_id, min_loaded_count=2):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先查看前两张预览图")
        self._apply_acceptance(session, request, response)
        session.commit()
        return self._to_request_item(session, request, user_id, viewer_role_mask)

    def record_preview_view(self, session: Session, request_id: int, user_id: int, payload: RequestPreviewViewPayload) -> None:
        self._bootstrap(session)
        request = self._require_request(session, request_id)
        if request.requester_id != user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作该求购")
        self._require_response_for_request(session, request_id, payload.responseId)
        entity = self.request_repo.find_preview_view(session, request_id, payload.responseId, user_id)
        if entity is None:
            entity = RequestPreviewViewRecord(
                request_id=request_id,
                response_id=payload.responseId,
                viewer_id=user_id,
                loaded_count=max(0, int(payload.loadedCount or 0)),
            )
        elif int(payload.loadedCount or 0) > entity.loaded_count:
            entity.loaded_count = int(payload.loadedCount or 0)
        self.request_repo.save_preview_view(session, entity)
        session.commit()

    def submit_dispute(self, session: Session, request_id: int, user_id: int, payload: RequestDisputePayload) -> dict[str, Any]:
        self._bootstrap(session)
        self._process_timeouts(session)
        request = self._require_request(session, request_id)
        if request.requester_id != user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作该求购")
        if request.status != REQUEST_STATUS_OPEN:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前求购不可仲裁")
        if request.accepted_response_id is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该求购已采纳")
        if self.request_repo.find_pending_arbitration(session, request_id) is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仲裁处理中，请耐心等待")
        response = self._require_response_for_request(session, request_id, payload.responseId)
        if response.material_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="应答需关联资料")
        if not self.request_repo.has_preview_view(session, request_id, payload.responseId, user_id, min_loaded_count=2):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先查看前两张预览图")
        entity = RequestArbitrationRecord(
            id=self.request_repo.next_arbitration_id(session),
            source="local",
            request_id=request_id,
            response_id=response.id,
            requester_id=request.requester_id,
            responder_id=response.responder_id,
            reason=payload.reason.strip(),
            status=ARBITRATION_STATUS_PENDING,
        )
        self.request_repo.save_arbitration(session, entity)
        request.status = REQUEST_STATUS_DISPUTED
        self.request_repo.save_request(session, request)
        session.commit()
        return self._to_request_item(session, request, user_id, None)

    def decide_arbitration(self, session: Session, arbitration_id: int, admin_user_id: int, payload: RequestArbitrationDecisionPayload) -> dict[str, Any]:
        self._bootstrap(session)
        arbitration = self.request_repo.get_arbitration(session, arbitration_id)
        if arbitration is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="仲裁记录不存在")
        if arbitration.status != ARBITRATION_STATUS_PENDING:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仲裁已处理")
        request = self._require_request(session, arbitration.request_id)
        response = self._require_response_for_request(session, request.id, arbitration.response_id)
        decision = payload.decision.strip().upper()
        if decision == "APPROVE":
            self._apply_acceptance(session, request, response)
            arbitration.status = ARBITRATION_STATUS_APPROVED
        elif decision == "REFUND":
            request.status = REQUEST_STATUS_REFUNDING
            self._refund_request_contributions(session, request, reason="仲裁退款")
            arbitration.status = ARBITRATION_STATUS_REFUNDED if request.status == REQUEST_STATUS_REFUNDED else ARBITRATION_STATUS_REFUNDING
        elif decision == "REVISION":
            request.status = REQUEST_STATUS_REVISION_REQUIRED
            self.request_repo.save_request(session, request)
            arbitration.status = ARBITRATION_STATUS_REVISION
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未知处理结果")
        arbitration.admin_note = self._strip(payload.adminNote)
        arbitration.decided_by_user_id = admin_user_id
        arbitration.decided_at = datetime.now(UTC)
        self.request_repo.save_arbitration(session, arbitration)
        session.commit()
        admin_user = self.auth_repo.find_user_by_id(session, admin_user_id)
        return self._to_request_item(session, request, admin_user_id, admin_user.role_mask if admin_user else None)

    def cancel_contribution(self, session: Session, contribution_id: int, user_id: int) -> dict[str, Any]:
        self._bootstrap(session)
        self._process_timeouts(session)
        contribution = self.request_repo.get_contribution(session, contribution_id)
        if contribution is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="跟购记录不存在")
        if contribution.contributor_id != user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权结束该记录")
        if contribution.status != CONTRIBUTION_STATUS_PAID:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前记录无法结束")
        request = self._require_request(session, contribution.request_id)
        if request.status != REQUEST_STATUS_OPEN or request.accepted_response_id is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="求购当前不可结束贡献")
        contribution.status = CONTRIBUTION_STATUS_REFUNDING
        self.request_repo.save_contribution(session, contribution)
        contribution.status = CONTRIBUTION_STATUS_REFUNDED
        self.request_repo.save_contribution(session, contribution)
        self._apply_refund_to_request(request, contribution.amount_cents)
        session.commit()
        return request_contribution_item(contribution)

    def update_contribution_deadline(self, session: Session, contribution_id: int, user_id: int, payload: RequestContributionDeadlinePayload) -> dict[str, Any]:
        self._bootstrap(session)
        contribution = self.request_repo.get_contribution(session, contribution_id)
        if contribution is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="跟购记录不存在")
        if contribution.contributor_id != user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权修改该记录")
        if contribution.status != CONTRIBUTION_STATUS_PAID:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅可修改已支付记录")
        request = self._require_request(session, contribution.request_id)
        if request.status != REQUEST_STATUS_OPEN:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="求购已结束，无法修改期限")
        tier = self._normalize_tier(payload.deadlineTier, contribution.deadline_tier)
        base = self._normalize_dt(contribution.paid_at or contribution.created_at) or datetime.now(UTC)
        next_deadline = self._compute_deadline_datetime(base, tier)
        current_deadline = self._normalize_dt(contribution.deadline_at)
        if current_deadline is not None and next_deadline is not None and next_deadline <= current_deadline:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅允许延长期限")
        if current_deadline is None and next_deadline is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="期限已为不限，无需修改")
        contribution.deadline_tier = tier
        contribution.deadline_at = next_deadline
        self.request_repo.save_contribution(session, contribution)
        session.commit()
        return request_contribution_item(contribution)

    def _bootstrap(self, session: Session) -> dict[str, Any]:
        seed = self.read_repo.load_seed()
        self.material_repo.ensure_seed_bootstrap(session, seed)
        self.request_repo.ensure_seed_bootstrap(session, seed)
        return seed

    def run_scheduled_refunds(self, session: Session) -> dict[str, int]:
        return self.run_request_maintenance(session)

    def run_request_maintenance(self, session: Session) -> dict[str, int]:
        self._bootstrap(session)
        processed = self._process_timeouts(session)
        return {"processed": processed}

    def mark_contribution_paid_by_out_trade_no(
        self,
        session: Session,
        *,
        out_trade_no: str,
        trade_no: str | None,
        amount_cents: int | None,
    ) -> dict[str, str]:
        self._bootstrap(session)
        contribution = self.request_repo.find_contribution_by_out_trade_no(session, out_trade_no)
        if contribution is None:
            return {"status": "NOT_FOUND"}
        expected_amount = int(contribution.amount_cents or 0)
        if amount_cents is not None and expected_amount != int(amount_cents):
            return {"status": "AMOUNT_MISMATCH"}
        if contribution.status == CONTRIBUTION_STATUS_PAID:
            return {"status": "DUPLICATE"}
        self._mark_contribution_paid(session, contribution)
        if trade_no:
            contribution.trade_no = trade_no
            contribution.pay_channel = "alipay_page"
            self.request_repo.save_contribution(session, contribution)
        session.commit()
        return {"status": "PAID"}

    def _process_timeouts(self, session: Session) -> int:
        now = datetime.now(UTC)
        changed = False
        processed = 0
        processed_request_ids: set[int] = set()
        arbitration_threshold = now - timedelta(hours=ARBITRATION_TIMEOUT_HOURS)
        for arbitration in self.request_repo.list_timed_out_pending_arbitrations(session, arbitration_threshold):
            if arbitration.source == "seed":
                continue
            request = self.request_repo.get_request(session, arbitration.request_id)
            if request is None:
                continue
            request.status = REQUEST_STATUS_REFUNDING
            self._refund_request_contributions(session, request, reason="仲裁超时自动退款")
            arbitration.status = ARBITRATION_STATUS_REFUNDED if request.status == REQUEST_STATUS_REFUNDED else ARBITRATION_STATUS_REFUNDING
            arbitration.decided_at = now
            self.request_repo.save_arbitration(session, arbitration)
            changed = True
            processed += 1
            processed_request_ids.add(int(request.id))

        for request in self.request_repo.list_timed_out_unanswered_requests(
            session,
            created_before=now - timedelta(hours=NO_ACCEPT_HOURS),
        ):
            if int(request.id) in processed_request_ids:
                continue
            self._refund_request_contributions(session, request, reason="48 小时未验收自动退款")
            changed = True
            processed += 1
            processed_request_ids.add(int(request.id))

        for request in self.request_repo.list_requests_with_expired_delivery_window(
            session,
            latest_deadline_before=now - timedelta(days=NO_DELIVERY_DAYS),
        ):
            if int(request.id) in processed_request_ids:
                continue
            self._refund_request_contributions(session, request, reason="45 天未交付自动退款")
            changed = True
            processed += 1
            processed_request_ids.add(int(request.id))
        if changed:
            session.commit()
        else:
            session.flush()
        return processed

    def _upsert_response(
        self,
        session: Session,
        *,
        request_id: int,
        user_id: int,
        material_id: int | None,
        message: str | None,
    ) -> RequestResponseRecord:
        seed = self.read_repo.load_seed()
        request = self._require_request(session, request_id)
        if request.status not in {REQUEST_STATUS_OPEN, REQUEST_STATUS_REVISION_REQUIRED}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该求购暂不可应答")
        if request.requester_id == user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能应答自己的求购")
        response = self.request_repo.find_response_by_request_and_responder(session, request_id, user_id)
        is_new = response is None
        if is_new and int(request.response_count or 0) > 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="已有应答，暂不可应答")
        user = self._require_user(session, user_id)
        if response is None:
            response = RequestResponseRecord(
                id=self.request_repo.next_response_id(session, seed),
                source="local",
                request_id=request_id,
                responder_id=user_id,
                responder_name=user.nickname or user.username,
                revision_count=0,
            )
        if material_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请上传资料作为应答")
        material = self.material_repo.get_material(session, material_id)
        if material is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")
        if material.uploader_id != user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能关联自己的资料")
        self._ensure_preview_ready(material)
        if not is_new and int(response.revision_count or 0) >= 2:
            self._enter_auto_arbitration(session, request, response, "超过修订次数自动进入仲裁")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="已超过可修改次数，已进入仲裁")
        if not is_new:
            response.revision_count = int(response.revision_count or 0) + 1
        response.message = message or response.message or "已上传资料"
        response.material_id = material_id
        self.request_repo.save_response(session, response)
        if is_new:
            request.response_count = int(request.response_count or 0) + 1
            self.request_repo.save_request(session, request)
        if request.status == REQUEST_STATUS_REVISION_REQUIRED:
            request.status = REQUEST_STATUS_OPEN
            self.request_repo.save_request(session, request)
        return response

    def _apply_acceptance(self, session: Session, request: RequestRecord, response: RequestResponseRecord) -> None:
        if request.accepted_response_id is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该求购已采纳")
        request.accepted_response_id = response.id
        request.accepted_at = datetime.now(UTC)
        request.status = REQUEST_STATUS_FULFILLED
        request.settled_at = request.accepted_at
        self.request_repo.save_request(session, request)

    def _refund_request_contributions(self, session: Session, request: RequestRecord, *, reason: str) -> None:
        _ = reason
        contributions = self.request_repo.list_contributions(session, request.id)
        active = [item for item in contributions if item.status in {CONTRIBUTION_STATUS_PAID, CONTRIBUTION_STATUS_REFUNDING}]
        if not active:
            request.status = REQUEST_STATUS_REFUNDED
            request.settled_at = datetime.now(UTC)
            self.request_repo.save_request(session, request)
            return
        all_refunded = True
        for contribution in active:
            contribution.status = CONTRIBUTION_STATUS_REFUNDING
            self.request_repo.save_contribution(session, contribution)
            contribution.status = CONTRIBUTION_STATUS_REFUNDED
            self.request_repo.save_contribution(session, contribution)
            self._apply_refund_to_request(request, contribution.amount_cents)
            if contribution.status != CONTRIBUTION_STATUS_REFUNDED:
                all_refunded = False
        request.status = REQUEST_STATUS_REFUNDED if all_refunded else REQUEST_STATUS_REFUNDING
        request.settled_at = datetime.now(UTC)
        self.request_repo.save_request(session, request)

    def _apply_refund_to_request(self, request: RequestRecord, amount_cents: int | None) -> None:
        request.funded_amount_cents = max(0, int(request.funded_amount_cents or 0) - int(amount_cents or 0))
        request.contribution_count = max(0, int(request.contribution_count or 0) - 1)
        if request.contribution_count == 0:
            request.max_contribution_amount_cents = 0

    def _create_contribution(
        self,
        session: Session,
        *,
        request: RequestRecord,
        contributor_id: int,
        contributor_name: str,
        amount_cents: int,
        contribution_type: str,
        deadline_tier: str,
        status_value: str,
        seed: dict[str, Any],
    ) -> RequestContributionRecord:
        entity = RequestContributionRecord(
            id=self.request_repo.next_contribution_id(session, seed),
            source="local",
            request_id=request.id,
            contributor_id=contributor_id,
            contributor_name=contributor_name,
            type=contribution_type,
            amount_cents=amount_cents,
            status=status_value,
            deadline_tier=deadline_tier,
            deadline_at=self._compute_deadline_datetime(datetime.now(UTC), deadline_tier),
            out_trade_no=self.request_repo.build_out_trade_no(),
        )
        self.request_repo.save_contribution(session, entity)
        return entity

    def _mark_contribution_paid(self, session: Session, contribution: RequestContributionRecord) -> None:
        if contribution.status == CONTRIBUTION_STATUS_PAID:
            return
        contribution.status = CONTRIBUTION_STATUS_PAID
        contribution.trade_no = f"TRADE{contribution.id}"
        contribution.pay_channel = "local_page"
        contribution.paid_at = datetime.now(UTC)
        if contribution.deadline_tier:
            contribution.deadline_at = self._compute_deadline_datetime(contribution.paid_at, contribution.deadline_tier)
        self.request_repo.save_contribution(session, contribution)
        request = self._require_request(session, contribution.request_id)
        request.funded_amount_cents = int(request.funded_amount_cents or 0) + int(contribution.amount_cents or 0)
        request.contribution_count = int(request.contribution_count or 0) + 1
        request.max_contribution_amount_cents = max(int(request.max_contribution_amount_cents or 0), int(contribution.amount_cents or 0))
        if contribution.type == TYPE_OWNER and request.status == REQUEST_STATUS_PENDING_PAYMENT:
            request.status = REQUEST_STATUS_OPEN
        self.request_repo.save_request(session, request)

    def _enter_auto_arbitration(self, session: Session, request: RequestRecord, response: RequestResponseRecord, reason: str) -> None:
        if self.request_repo.find_pending_arbitration(session, request.id) is not None:
            return
        entity = RequestArbitrationRecord(
            id=self.request_repo.next_arbitration_id(session),
            source="local",
            request_id=request.id,
            response_id=response.id,
            requester_id=request.requester_id,
            responder_id=response.responder_id,
            reason=reason,
            status=ARBITRATION_STATUS_PENDING,
        )
        self.request_repo.save_arbitration(session, entity)
        request.status = REQUEST_STATUS_DISPUTED
        self.request_repo.save_request(session, request)

    def _require_request(self, session: Session, request_id: int) -> RequestRecord:
        request = self.request_repo.get_request(session, request_id)
        if request is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="求购不存在")
        return request

    def _require_request_with_access(self, session: Session, request_id: int, viewer_id: int, viewer_role_mask: int | None) -> RequestRecord:
        request = self._require_request(session, request_id)
        is_owner = request.requester_id == viewer_id
        can_manage_all = self._can_manage_all(viewer_role_mask)
        if not is_owner and not can_manage_all and (not self._is_publicly_visible(request) or self._should_hide_by_early_exit(session, request)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="求购不存在")
        return request

    def _require_response_for_request(self, session: Session, request_id: int, response_id: int) -> RequestResponseRecord:
        response = self.request_repo.get_response(session, response_id)
        if response is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="应答不存在")
        if response.request_id != request_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="应答不属于该求购")
        return response

    def _require_user(self, session: Session, user_id: int):
        user = self.auth_repo.find_user_by_id(session, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        return user

    def _ensure_preview_ready(self, material: MaterialRecord) -> None:
        if (material.preview_status or "").lower() != "done":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="预览尚未准备好")
        preview_pages = int(material.preview_pages or 0)
        custom_previews = self._loads(material.custom_preview_images_json)
        if max(preview_pages, len(custom_previews)) < 2:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="预览图不足")

    def _to_request_item(
        self,
        session: Session,
        item: RequestRecord,
        viewer_id: int | None,
        viewer_role_mask: int | None,
        *,
        responded_ids: set[int] | None = None,
    ) -> dict[str, Any]:
        is_owner = viewer_id is not None and item.requester_id == viewer_id
        can_manage_all = self._can_manage_all(viewer_role_mask)
        requester_name = item.requester_name
        if item.anonymous and not is_owner and not can_manage_all:
            requester_name = None
        responded = False
        if viewer_id is not None:
            if responded_ids is not None:
                responded = int(item.id) in responded_ids
            else:
                responded = self.request_repo.find_response_by_request_and_responder(session, item.id, viewer_id) is not None
        return {
            "id": item.id,
            "course": item.course,
            "keyword": item.keyword,
            "school": item.school,
            "college": item.college,
            "major": item.major,
            "budget": self._to_yuan(item.budget_cents),
            "fundedAmount": self._to_yuan(item.funded_amount_cents),
            "contributionCount": item.contribution_count,
            "deadline": item.deadline.isoformat() if item.deadline else None,
            "urgencyTier": item.urgency_tier,
            "creatorFloor": self._to_yuan(item.creator_floor_cents),
            "previewRequirement": item.preview_requirement,
            "anonymous": bool(item.anonymous),
            "requesterName": requester_name,
            "responseCount": int(item.response_count or 0),
            "responded": responded,
            "owner": is_owner,
            "acceptedResponseId": item.accepted_response_id,
            "status": item.status,
            "createdAt": serialize_datetime(item.created_at),
        }

    def _normalize_tier(self, value: str | None, fallback: str | None) -> str:
        normalized = (value or "").strip().upper()
        if normalized in OWNER_MINIMUMS:
            return normalized
        fallback_normalized = (fallback or "FLEX").strip().upper()
        if fallback_normalized in OWNER_MINIMUMS:
            return fallback_normalized
        return "FLEX"

    def _normalize_money(self, value: int | None) -> int | None:
        if value is None or value <= 0:
            return None
        return int(value)

    def _compute_deadline_datetime(self, base: datetime, tier: str | None) -> datetime | None:
        normalized = self._normalize_tier(tier, "FLEX")
        start = base if base.tzinfo is not None else base.replace(tzinfo=UTC)
        if normalized == "24H":
            return start + timedelta(days=1)
        if normalized == "WEEK":
            return start + timedelta(days=7)
        if normalized == "MONTH":
            return start + timedelta(days=30)
        return None

    def _compute_deadline_date(self, base: datetime, tier: str | None):
        deadline = self._compute_deadline_datetime(base, tier)
        return None if deadline is None else deadline.date()

    def _build_local_pay_form(self, out_trade_no: str) -> str:
        return (
            "<form method=\"GET\" action=\"/pay/result\">"
            f"<input type=\"hidden\" name=\"orderNo\" value=\"{out_trade_no}\" />"
            "</form>"
        )

    def _is_publicly_visible(self, request: RequestRecord) -> bool:
        return request.status == REQUEST_STATUS_OPEN

    def _should_hide_by_early_exit(self, session: Session, request: RequestRecord) -> bool:
        contributions = self.request_repo.list_paid_like_contributions(session, request.id)
        if not contributions:
            return False
        refunded = sum(1 for item in contributions if item.status == CONTRIBUTION_STATUS_REFUNDED)
        return refunded >= len(contributions)

    def _can_manage_all(self, role_mask: int | None) -> bool:
        return has_role(role_mask, ROLE_ADMIN) or has_role(role_mask, ROLE_DEVELOPER)

    def _strip(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    def _to_yuan(self, cents: int | None) -> float | None:
        return amount_to_yuan(cents)

    def _created_ts(self, entity: Any) -> float:
        value = serialize_datetime(entity.created_at) if getattr(entity, "created_at", None) else None
        return parse_iso_datetime(value).timestamp()

    def _normalize_dt(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    def _loads(self, value: str | None) -> list[str]:
        if not value:
            return []
        try:
            import json

            parsed = json.loads(value)
        except Exception:  # noqa: BLE001
            return []
        return [str(item) for item in parsed if isinstance(item, (str, int, float))]
