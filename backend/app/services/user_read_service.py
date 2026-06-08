from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import bindparam, inspect, text
from sqlalchemy.orm import Session

from app.core.profile_metadata import DEFAULT_FREE_DOWNLOAD_QUOTA, resolve_free_download_quota
from app.core.db import session_scope
from app.models.auth import AuthUser, LegacyAuthUser
from app.repos.auth_repo import AuthRepository, resolve_user_model
from app.repos.finance_repo import FinanceRepository
from app.repos.market_repo import MarketRepository
from app.repos.material_repo import MaterialRepository
from app.repos.read_api_repo import ReadApiRepository
from app.services.materials_serializers import load_json_list
from app.services.read_support import (
    DEFAULT_OUTPUT_TIMEZONE,
    ROLE_ADMIN,
    ROLE_DEVELOPER,
    clamp_limit,
    compat_serialize_datetime,
    duration_to_iso,
    has_role,
    parse_iso_datetime,
    serialize_datetime,
    serialize_user_snapshot,
    unlimited_free_download,
)
from app.services.user_follow_service import UserFollowService


_TABLE_NAME_CACHE: dict[str, set[str]] = {}
_TABLE_COLUMN_CACHE: dict[tuple[str, str], set[str]] = {}


def _bind_cache_key(session: Session) -> str:
    bind = session.get_bind()
    try:
        return bind.engine.url.render_as_string(hide_password=True)
    except Exception:
        return str(bind)


def _table_names(session: Session) -> set[str]:
    cache_key = _bind_cache_key(session)
    cached = _TABLE_NAME_CACHE.get(cache_key)
    if cached is not None:
        return cached
    table_names = set(inspect(session.get_bind()).get_table_names())
    _TABLE_NAME_CACHE[cache_key] = table_names
    return table_names


def _table_columns(session: Session, table_name: str) -> set[str]:
    cache_key = (_bind_cache_key(session), table_name)
    cached = _TABLE_COLUMN_CACHE.get(cache_key)
    if cached is not None:
        return cached
    column_names = {column["name"] for column in inspect(session.get_bind()).get_columns(table_name)}
    _TABLE_COLUMN_CACHE[cache_key] = column_names
    return column_names


def _table_has_column(session: Session, table_name: str, column_name: str) -> bool:
    return table_name in _table_names(session) and column_name in _table_columns(session, table_name)


class UserReadService:
    def __init__(
        self,
        repo: ReadApiRepository,
        auth_repo: AuthRepository,
        user_follow_service: UserFollowService,
        material_repo: MaterialRepository,
        market_repo: MarketRepository,
        finance_repo: FinanceRepository,
    ) -> None:
        self.repo = repo
        self.auth_repo = auth_repo
        self.user_follow_service = user_follow_service
        self.material_repo = material_repo
        self.market_repo = market_repo
        self.finance_repo = finance_repo

    def get_overview(self, session: Session, user_id: int) -> dict[str, Any]:
        seed = self.repo.load_seed()
        user = self._require_user_snapshot(session, user_id, seed=seed)
        profile_seed = (seed.get("profileSummary") or {}).get(str(user_id), {})
        purchases = list(profile_seed.get("purchases") or [])
        market_wants = self._build_market_wants(session, seed, user_id)
        uploads = self.get_user_uploads(session, user_id, user_id, user.get("roleMask"), limit=None, seed=seed)
        market_listings = self.get_user_market_listings(session, user_id, user_id, user.get("roleMask"), limit=None, seed=seed)
        admin_notes = list(profile_seed.get("adminNotes") or [])
        totals = profile_seed.get("totals") or {}
        return {
            "purchases": purchases,
            "uploads": uploads,
            "marketWants": market_wants,
            "marketListings": market_listings,
            "adminNotes": admin_notes,
            "freeDownloadStatus": self.get_free_download_status(session, user_id, seed=seed),
            "hasNewAlerts": bool(profile_seed.get("hasNewAlerts")),
            "totalDownloads": int(totals.get("totalDownloads", sum(item.get("downloadCount", 0) or 0 for item in uploads))),
            "uniqueDownloaders": int(totals.get("uniqueDownloaders", 0)),
            "totalEarnings": float(totals.get("totalEarnings", 0)),
        }

    async def get_overview_async(self, user_id: int) -> dict[str, Any]:
        if not self._allows_concurrent_profile_reads():
            with session_scope() as session:
                return self.get_overview(session, user_id)
        seed, profile_seed, totals = await asyncio.to_thread(self._load_overview_base, user_id)
        market_wants_task = asyncio.to_thread(self._call_with_new_session, self._load_market_wants_for_overview, seed, user_id)
        uploads_task = asyncio.to_thread(self._call_with_new_session, self._load_uploads_for_overview, seed, user_id)
        market_listings_task = asyncio.to_thread(self._call_with_new_session, self._load_market_listings_for_overview, seed, user_id)
        free_download_task = asyncio.to_thread(self._call_with_new_session, self.get_free_download_status, user_id, seed=seed)
        market_wants, uploads, market_listings, free_download_status = await asyncio.gather(
            market_wants_task,
            uploads_task,
            market_listings_task,
            free_download_task,
        )
        return {
            "purchases": list(profile_seed.get("purchases") or []),
            "uploads": uploads,
            "marketWants": market_wants,
            "marketListings": market_listings,
            "adminNotes": list(profile_seed.get("adminNotes") or []),
            "freeDownloadStatus": free_download_status,
            "hasNewAlerts": bool(profile_seed.get("hasNewAlerts")),
            "totalDownloads": int(totals.get("totalDownloads", sum(item.get("downloadCount", 0) or 0 for item in uploads))),
            "uniqueDownloaders": int(totals.get("uniqueDownloaders", 0)),
            "totalEarnings": float(totals.get("totalEarnings", 0)),
        }

    def get_public_profile(
        self,
        session: Session,
        viewer_id: int,
        viewer_role_mask: int | None,
        target_user_id: int,
    ) -> dict[str, Any]:
        seed = self.repo.load_seed()
        target = self._require_accessible_user(session, viewer_id, viewer_role_mask, target_user_id, seed=seed)
        is_owner = viewer_id == target_user_id
        email_visible = is_owner or not bool(target.get("emailPrivacy"))
        can_view_payout_qr = is_owner or has_role(viewer_role_mask, ROLE_ADMIN)
        uploads = self.get_user_uploads(session, viewer_id, target_user_id, viewer_role_mask, limit=5, seed=seed)
        listings = self.get_user_market_listings(session, viewer_id, target_user_id, viewer_role_mask, limit=5, seed=seed)
        follower_count = self._followers_count(session, seed, target_user_id)
        following_count = self._following_count(session, seed, target_user_id)
        purchase_count = self._purchase_count(seed, target_user_id)
        sale_count = self._sale_count(session, seed, target_user_id)
        return {
            "id": target["id"],
            "username": target["username"],
            "nickname": target["nickname"] or target["username"],
            "signature": target.get("signature"),
            "school": target.get("school"),
            "college": target.get("college"),
            "major": target.get("major"),
            "gradeStages": list(target.get("gradeStages") or []),
            "avatar": target.get("avatar"),
            "email": target.get("email") if email_visible else None,
            "emailVisible": email_visible,
            "payoutQrUrl": target.get("payoutQrUrl") if can_view_payout_qr else None,
            "legendaryContributorUntil": target.get("legendaryContributorUntil"),
            "uploadCount": self._count_user_uploads(session, target_user_id, seed=seed),
            "marketCount": self._count_user_market_listings(session, target_user_id, seed=seed),
            "purchaseCount": purchase_count,
            "saleCount": sale_count,
            "followersCount": follower_count,
            "followingCount": following_count,
            "isFollowing": self._is_following(session, seed, viewer_id, target_user_id),
            "recentUploads": uploads,
            "recentMarketListings": listings,
        }

    async def get_public_profile_async(
        self,
        viewer_id: int,
        viewer_role_mask: int | None,
        target_user_id: int,
    ) -> dict[str, Any]:
        if not self._allows_concurrent_profile_reads():
            with session_scope() as session:
                return self.get_public_profile(session, viewer_id, viewer_role_mask, target_user_id)
        base = await asyncio.to_thread(
            self._call_with_new_session,
            self._load_public_profile_base,
            viewer_id,
            viewer_role_mask,
            target_user_id,
        )
        material_summary_task = asyncio.to_thread(
            self._call_with_new_session,
            self._load_public_profile_material_summary,
            viewer_id,
            viewer_role_mask,
            target_user_id,
        )
        market_summary_task = asyncio.to_thread(
            self._call_with_new_session,
            self._load_public_profile_market_summary,
            viewer_id,
            viewer_role_mask,
            target_user_id,
        )
        relationship_task = asyncio.to_thread(
            self._call_with_new_session,
            self._load_public_profile_relationships,
            viewer_id,
            target_user_id,
        )
        material_summary, market_summary, relationships = await asyncio.gather(
            material_summary_task,
            market_summary_task,
            relationship_task,
        )
        base.update(
            {
                "uploadCount": material_summary["uploadCount"],
                "marketCount": market_summary["marketCount"],
                "saleCount": material_summary["saleCount"],
                "followersCount": relationships["followersCount"],
                "followingCount": relationships["followingCount"],
                "isFollowing": relationships["isFollowing"],
                "recentUploads": material_summary["recentUploads"],
                "recentMarketListings": market_summary["recentMarketListings"],
            }
        )
        return base

    def get_user_uploads(
        self,
        session: Session,
        viewer_id: int,
        target_user_id: int,
        viewer_role_mask: int | None,
        limit: int | None,
        *,
        seed: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self._require_accessible_user(session, viewer_id, viewer_role_mask, target_user_id, seed=seed)
        if self._uses_legacy_user_table(session):
            return self._compat_get_user_uploads(session, target_user_id, limit)
        self._bootstrap_content(session, seed=seed)
        safe_limit = clamp_limit(limit, max_value=100)
        include_tags = _table_has_column(session, "materials", "tags_json")
        items = [
            self._to_upload_record(material, include_tags=include_tags)
            for material in self.material_repo.list_visible_materials_for_uploader(session, target_user_id, limit=safe_limit)
        ]
        return items[:safe_limit] if safe_limit else items

    def get_user_market_listings(
        self,
        session: Session,
        viewer_id: int,
        target_user_id: int,
        viewer_role_mask: int | None,
        limit: int | None,
        *,
        seed: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self._require_accessible_user(session, viewer_id, viewer_role_mask, target_user_id, seed=seed)
        if self._uses_legacy_user_table(session):
            return self._compat_get_user_market_listings(session, target_user_id, limit)
        self._bootstrap_content(session, seed=seed)
        safe_limit = clamp_limit(limit, max_value=100)
        items = [
            self._to_market_sell_record(item)
            for item in self.market_repo.list_visible_items_for_seller(session, target_user_id, limit=safe_limit)
        ]
        return items[:safe_limit] if safe_limit else items

    def get_free_download_status(self, session: Session, user_id: int, *, seed: dict[str, Any] | None = None) -> dict[str, Any]:
        snapshot = self._require_user_snapshot(session, user_id, seed=seed)
        role_mask = snapshot.get("roleMask")
        unlimited = unlimited_free_download(role_mask)
        remaining = 2_147_483_647 if unlimited else DEFAULT_FREE_DOWNLOAD_QUOTA
        if not unlimited and snapshot.get("freeDownloadQuota") is not None:
            remaining = resolve_free_download_quota(snapshot.get("freeDownloadQuota"))
        return {"remaining": remaining, "unlimited": unlimited}

    def get_creator_metrics(self, session: Session, user_id: int) -> dict[str, Any]:
        seed = self.repo.load_seed()
        self._require_user_snapshot(session, user_id, seed=seed)
        payload = (seed.get("creatorMetrics") or {}).get(str(user_id), {})
        current_dt = datetime.now(UTC)
        week_start = self._start_of_week(current_dt)
        local_orders = self.finance_repo.list_paid_orders_for_creator_between(session, user_id, week_start, current_dt)
        has_local_metrics = bool(local_orders)
        reference_dt = parse_iso_datetime(payload.get("weekEnd")) if (payload.get("weekEnd") and not has_local_metrics) else current_dt
        schedule = self.finance_repo.get_payout_schedule(session)
        if schedule is not None and schedule.next_payout_date is not None and has_local_metrics:
            next_payout_dt = datetime.combine(schedule.next_payout_date, datetime.min.time(), tzinfo=DEFAULT_OUTPUT_TIMEZONE).astimezone(UTC)
        else:
            next_payout_dt = (
                parse_iso_datetime(payload.get("nextPayoutDate"))
                if payload.get("nextPayoutDate")
                else self._next_saturday_midnight(reference_dt)
            )

        if has_local_metrics:
            week_sales = len(local_orders)
            gross_cents = sum(int(order.amount or 0) for order in local_orders)
            net_cents = sum(int(order.creator_payable_amount or 0) for order in local_orders)
            fee_cents = sum(int(order.platform_fee_amount or 0) for order in local_orders)
            week_gross = Decimal(gross_cents).scaleb(-2)
            week_net = Decimal(net_cents).scaleb(-2)
            commission_rate = Decimal("0") if gross_cents <= 0 else (Decimal(fee_cents) / Decimal(gross_cents)).quantize(Decimal("0.0001"))
        else:
            week_sales = int(payload.get("weekSales", 0))
            week_gross = Decimal(str(payload.get("weekGross", 0)))
            commission_rate = Decimal(str(payload.get("commissionRate", 0)))
            week_net_value = payload.get("weekNet")
            if week_net_value is None:
                week_net_value = float((week_gross * (Decimal("1") - commission_rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            week_net = Decimal(str(week_net_value))

        countdown = duration_to_iso(max(next_payout_dt - reference_dt, timedelta(seconds=0)))
        return {
            "nextPayoutDate": next_payout_dt.isoformat(),
            "countdown": countdown,
            "weekSales": week_sales,
            "weekGross": float(week_gross),
            "weekNet": float(week_net),
            "commissionRate": float(commission_rate),
        }

    def _require_user_snapshot(self, session: Session, user_id: int, *, seed: dict[str, Any] | None = None) -> dict[str, Any]:
        snapshot = self._resolve_user_snapshot(session, user_id, seed=seed)
        if snapshot is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        return snapshot

    def _require_accessible_user(
        self,
        session: Session,
        viewer_id: int,
        viewer_role_mask: int | None,
        target_user_id: int,
        *,
        seed: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        snapshot = self._require_user_snapshot(session, target_user_id, seed=seed)
        auth_user = self.auth_repo.find_user_by_id(session, target_user_id)
        is_owner = viewer_id == target_user_id
        is_privileged = has_role(viewer_role_mask, ROLE_ADMIN) or has_role(viewer_role_mask, ROLE_DEVELOPER)
        if auth_user is not None and auth_user.status == "hidden" and not (is_owner or is_privileged):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        return snapshot

    def _resolve_user_snapshot(self, session: Session, user_id: int, *, seed: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if seed is None:
            seed = self.repo.load_seed()
        seed_user = (seed.get("users") or {}).get(str(user_id))
        auth_user = self.auth_repo.find_user_by_id(session, user_id)
        if seed_user is None and auth_user is None:
            return None
        return serialize_user_snapshot(seed_user, auth_user)

    def _build_market_wants(self, session: Session, seed: dict[str, Any], user_id: int) -> list[dict[str, Any]]:
        self._bootstrap_content(session, seed=seed)
        wanted_ids = set(self.market_repo.wanted_ids_for_user(session, user_id))
        items_by_id = {int(item.id): item for item in self.market_repo.list_items_by_ids(session, list(wanted_ids))}
        results: list[dict[str, Any]] = []
        for item_id in wanted_ids:
            item = items_by_id.get(int(item_id))
            if item is None or item.status in {"REMOVED", "HIDDEN"}:
                continue
            results.append(
                {
                    "itemId": item.id,
                    "title": item.title,
                    "price": item.price_cents / 100.0,
                    "wantCount": int(item.want_count or 0),
                    "sellerName": item.seller_name,
                    "createdAt": serialize_datetime(item.created_at),
                }
            )
        results.sort(key=lambda item: -parse_iso_datetime(item.get("createdAt")).timestamp())
        return results

    def _followers_of(self, seed: dict[str, Any], target_user_id: int) -> list[int]:
        follows = (seed.get("relationships") or {}).get("follows", {})
        return [
            int(user_id)
            for user_id, following in follows.items()
            if int(target_user_id) in {int(item) for item in following}
        ]

    def _following_of(self, seed: dict[str, Any], target_user_id: int) -> list[int]:
        follows = (seed.get("relationships") or {}).get("follows", {})
        return [int(item) for item in follows.get(str(target_user_id), [])]

    def _purchase_count(self, seed: dict[str, Any], user_id: int) -> int:
        purchases = (seed.get("profileSummary") or {}).get(str(user_id), {}).get("purchases", [])
        return len(purchases)

    def _start_of_week(self, now: datetime) -> datetime:
        local = now.astimezone(DEFAULT_OUTPUT_TIMEZONE)
        monday = local - timedelta(days=local.weekday())
        return monday.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)

    def _sale_count(self, session: Session, seed: dict[str, Any], user_id: int) -> int:
        if self._uses_legacy_user_table(session):
            row = session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM materials
                    WHERE uploader_id = :user_id
                      AND deleted_at IS NULL
                      AND LOWER(status) NOT IN ('removed', 'hidden')
                      AND is_free = 0
                    """
                ),
                {"user_id": user_id},
            ).scalar()
            return int(row or 0)
        self._bootstrap_content(session, seed=seed)
        return self.material_repo.count_paid_visible_materials_for_uploader(session, user_id)

    def _bootstrap_content(self, session: Session, *, seed: dict[str, Any] | None = None) -> dict[str, Any]:
        if seed is None:
            seed = self.repo.load_seed()
        self.material_repo.ensure_seed_bootstrap(session, seed)
        self.market_repo.ensure_seed_bootstrap(session, seed)
        return seed

    def _followers_count(self, session: Session, seed: dict[str, Any], target_user_id: int) -> int:
        if self.auth_repo.find_user_by_id(session, target_user_id) is None:
            return len(self._followers_of(seed, target_user_id))
        return self.user_follow_service.count_followers(session, target_user_id)

    def _following_count(self, session: Session, seed: dict[str, Any], target_user_id: int) -> int:
        if self.auth_repo.find_user_by_id(session, target_user_id) is None:
            return len(self._following_of(seed, target_user_id))
        return self.user_follow_service.count_following(session, target_user_id)

    def _is_following(self, session: Session, seed: dict[str, Any], viewer_id: int, target_user_id: int) -> bool:
        if viewer_id == target_user_id:
            return False
        if self.auth_repo.find_user_by_id(session, viewer_id) is None or self.auth_repo.find_user_by_id(session, target_user_id) is None:
            return viewer_id in self._followers_of(seed, target_user_id)
        return self.user_follow_service.is_following(session, follower_id=viewer_id, target_user_id=target_user_id)

    def _next_saturday_midnight(self, reference: datetime) -> datetime:
        days_until_saturday = (5 - reference.weekday()) % 7
        candidate = reference + timedelta(days=days_until_saturday)
        candidate = candidate.replace(hour=0, minute=0, second=0, microsecond=0)
        if candidate <= reference:
            candidate += timedelta(days=7)
        return candidate

    def _to_upload_item(self, material: dict[str, Any]) -> dict[str, Any]:
        return {
            "materialId": material["id"],
            "title": material["title"],
            "status": material.get("status", "VISIBLE"),
            "free": bool(material.get("free")),
            "price": float(material.get("price", 0)),
            "salesCount": int(material.get("salesCount", 0)),
            "downloadCount": int(material.get("downloadCount", 0)),
            "createdAt": material.get("createdAt"),
            "commentCount": int(material.get("commentCount", 0)),
            "likeCount": int(material.get("likeCount", 0)),
            "tags": list(material.get("tags") or []),
        }

    def _to_upload_record(self, material, *, include_tags: bool) -> dict[str, Any]:
        item = {
            "materialId": material.id,
            "title": material.title,
            "status": material.status,
            "free": bool(material.is_free),
            "price": material.price / 100.0,
            "salesCount": int(material.sales_count or 0),
            "downloadCount": int(material.download_count or 0),
            "createdAt": serialize_datetime(material.created_at),
            "commentCount": int(material.comment_count or 0),
            "likeCount": int(material.like_count or 0),
            "tags": [],
        }
        if include_tags:
            item["tags"] = load_json_list(material.tags_json)
        return item

    def _to_market_sell_item(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "itemId": item["id"],
            "title": item["title"],
            "price": float(item.get("price", 0)),
            "wantCount": int(item.get("wantCount", 0)),
            "status": item.get("status", "SALE"),
            "createdAt": item.get("createdAt"),
        }

    def _to_market_sell_record(self, item) -> dict[str, Any]:
        return {
            "itemId": item.id,
            "title": item.title,
            "price": item.price_cents / 100.0,
            "wantCount": int(item.want_count or 0),
            "status": item.status,
            "createdAt": serialize_datetime(item.created_at),
        }

    def _uses_legacy_user_table(self, session: Session) -> bool:
        return resolve_user_model(session) is LegacyAuthUser

    def _allows_concurrent_profile_reads(self) -> bool:
        return self.repo.load_seed() == {} and self.auth_repo is not None

    def _call_with_new_session(self, loader, *args, **kwargs):
        with session_scope() as session:
            return loader(session, *args, **kwargs)

    def _load_overview_base(self, user_id: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        with session_scope() as session:
            seed = self.repo.load_seed()
            self._require_user_snapshot(session, user_id, seed=seed)
            profile_seed = (seed.get("profileSummary") or {}).get(str(user_id), {})
            totals = profile_seed.get("totals") or {}
            return seed, profile_seed, totals

    def _load_market_wants_for_overview(self, session: Session, seed: dict[str, Any], user_id: int) -> list[dict[str, Any]]:
        return self._build_market_wants(session, seed, user_id)

    def _load_uploads_for_overview(self, session: Session, seed: dict[str, Any], user_id: int) -> list[dict[str, Any]]:
        return self.get_user_uploads(session, user_id, user_id, None, limit=None, seed=seed)

    def _load_market_listings_for_overview(self, session: Session, seed: dict[str, Any], user_id: int) -> list[dict[str, Any]]:
        return self.get_user_market_listings(session, user_id, user_id, None, limit=None, seed=seed)

    def _load_public_profile_base(
        self,
        session: Session,
        viewer_id: int,
        viewer_role_mask: int | None,
        target_user_id: int,
    ) -> dict[str, Any]:
        seed = self.repo.load_seed()
        target = self._require_accessible_user(session, viewer_id, viewer_role_mask, target_user_id, seed=seed)
        is_owner = viewer_id == target_user_id
        email_visible = is_owner or not bool(target.get("emailPrivacy"))
        can_view_payout_qr = is_owner or has_role(viewer_role_mask, ROLE_ADMIN)
        return {
            "id": target["id"],
            "username": target["username"],
            "nickname": target["nickname"] or target["username"],
            "signature": target.get("signature"),
            "school": target.get("school"),
            "college": target.get("college"),
            "major": target.get("major"),
            "gradeStages": list(target.get("gradeStages") or []),
            "avatar": target.get("avatar"),
            "email": target.get("email") if email_visible else None,
            "emailVisible": email_visible,
            "payoutQrUrl": target.get("payoutQrUrl") if can_view_payout_qr else None,
            "legendaryContributorUntil": target.get("legendaryContributorUntil"),
            "purchaseCount": self._purchase_count(seed, target_user_id),
        }

    def _load_public_profile_relationships(self, session: Session, viewer_id: int, target_user_id: int) -> dict[str, Any]:
        seed = self.repo.load_seed()
        return {
            "followersCount": self._followers_count(session, seed, target_user_id),
            "followingCount": self._following_count(session, seed, target_user_id),
            "isFollowing": self._is_following(session, seed, viewer_id, target_user_id),
        }

    def _load_public_profile_material_summary(
        self,
        session: Session,
        viewer_id: int,
        viewer_role_mask: int | None,
        target_user_id: int,
    ) -> dict[str, Any]:
        seed = self.repo.load_seed()
        return {
            "recentUploads": self.get_user_uploads(session, viewer_id, target_user_id, viewer_role_mask, 5, seed=seed),
            "uploadCount": self._count_user_uploads(session, target_user_id, seed=seed),
            "saleCount": self._sale_count(session, seed, target_user_id),
        }

    def _load_public_profile_market_summary(
        self,
        session: Session,
        viewer_id: int,
        viewer_role_mask: int | None,
        target_user_id: int,
    ) -> dict[str, Any]:
        seed = self.repo.load_seed()
        return {
            "recentMarketListings": self.get_user_market_listings(session, viewer_id, target_user_id, viewer_role_mask, 5, seed=seed),
            "marketCount": self._count_user_market_listings(session, target_user_id, seed=seed),
        }

    def _count_user_uploads(self, session: Session, target_user_id: int, *, seed: dict[str, Any] | None = None) -> int:
        if self._uses_legacy_user_table(session):
            row = session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM materials
                    WHERE uploader_id = :user_id
                      AND deleted_at IS NULL
                      AND LOWER(status) NOT IN ('removed', 'hidden')
                    """
                ),
                {"user_id": target_user_id},
            ).scalar()
            return int(row or 0)
        self._bootstrap_content(session, seed=seed)
        return self.material_repo.count_visible_materials_for_uploader(session, target_user_id)

    def _count_user_market_listings(self, session: Session, target_user_id: int, *, seed: dict[str, Any] | None = None) -> int:
        if self._uses_legacy_user_table(session):
            row = session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM market_items
                    WHERE seller_id = :user_id
                      AND LOWER(status) NOT IN ('removed', 'hidden')
                    """
                ),
                {"user_id": target_user_id},
            ).scalar()
            return int(row or 0)
        self._bootstrap_content(session, seed=seed)
        return self.market_repo.count_visible_items_for_seller(session, target_user_id)

    def _compat_get_user_uploads(self, session: Session, target_user_id: int, limit: int | None) -> list[dict[str, Any]]:
        safe_limit = clamp_limit(limit, max_value=100)
        sql = """
            SELECT
              m.id,
              m.title,
              m.status,
              m.is_free,
              m.price,
              m.sales_count,
              m.download_count,
              m.created_at,
              m.like_count
            FROM materials m
            WHERE m.uploader_id = :user_id
              AND m.deleted_at IS NULL
              AND LOWER(m.status) NOT IN ('removed', 'hidden')
            ORDER BY COALESCE(m.download_count, 0) DESC, m.created_at DESC, m.id DESC
        """
        params: dict[str, Any] = {"user_id": target_user_id}
        if safe_limit is not None:
            sql += "\nLIMIT :limit"
            params["limit"] = safe_limit
        rows = session.execute(text(sql), params).mappings().all()
        material_ids = [int(row["id"]) for row in rows]
        tags_by_material = self._compat_load_upload_tags(session, material_ids)
        return [
            self._compat_upload_row_to_item(
                row,
                tags=tags_by_material.get(int(row["id"])) if tags_by_material is not None else None,
            )
            for row in rows
        ]

    def _compat_load_upload_tags(self, session: Session, material_ids: list[int]) -> dict[int, list[str]] | None:
        if not material_ids:
            return {}
        if "material_tags" not in _table_names(session):
            return None
        stmt = text(
            """
            SELECT material_id, tag
            FROM material_tags
            WHERE material_id IN :material_ids
            ORDER BY id ASC
            """
        ).bindparams(bindparam("material_ids", expanding=True))
        rows = session.execute(stmt, {"material_ids": material_ids}).mappings().all()
        result: dict[int, list[str]] = {material_id: [] for material_id in material_ids}
        for row in rows:
            tag = row["tag"]
            if isinstance(tag, str) and tag.strip():
                result.setdefault(int(row["material_id"]), []).append(tag)
        return result

    def _compat_upload_row_to_item(self, row: Any, *, tags: list[str] | None) -> dict[str, Any]:
        item = {
            "materialId": int(row["id"]),
            "title": row["title"],
            "status": row["status"],
            "free": bool(row["is_free"]),
            "price": int(row["price"] or 0) / 100.0,
            "salesCount": int(row["sales_count"] or 0),
            "downloadCount": int(row["download_count"] or 0),
            "createdAt": compat_serialize_datetime(row["created_at"]),
            "commentCount": 0,
            "likeCount": int(row["like_count"] or 0),
            "tags": tags or [],
        }
        return item

    def _compat_get_user_market_listings(self, session: Session, target_user_id: int, limit: int | None) -> list[dict[str, Any]]:
        safe_limit = clamp_limit(limit, max_value=100)
        sql = """
            SELECT
              mi.id,
              mi.title,
              mi.price,
              mi.want_count,
              mi.status,
              mi.created_at
            FROM market_items mi
            WHERE mi.seller_id = :user_id
              AND LOWER(mi.status) NOT IN ('removed', 'hidden')
            ORDER BY COALESCE(mi.want_count, 0) DESC, mi.created_at DESC, mi.id DESC
        """
        params: dict[str, Any] = {"user_id": target_user_id}
        if safe_limit is not None:
            sql += "\nLIMIT :limit"
            params["limit"] = safe_limit
        rows = session.execute(text(sql), params).mappings().all()
        return [
            {
                "itemId": int(row["id"]),
                "title": row["title"],
                "price": int(row["price"] or 0) / 100.0,
                "wantCount": int(row["want_count"] or 0),
                "status": row["status"],
                "createdAt": compat_serialize_datetime(row["created_at"]),
            }
            for row in rows
        ]
