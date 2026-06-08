from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.community import ReportRecord
from app.repos.auth_repo import AuthRepository
from app.repos.comment_repo import CommentRepository
from app.repos.community_repo import CommunityRepository
from app.repos.market_repo import MarketRepository
from app.repos.material_repo import MaterialRepository
from app.repos.read_api_repo import ReadApiRepository
from app.schemas.reports import AdminReportUpdatePayload, ReportCreatePayload
from app.services.read_support import serialize_datetime


AUTO_HIDE_THRESHOLD = 3
REPORT_STATUSES = {"PENDING", "IN_PROGRESS", "RESOLVED", "REJECTED"}
TARGET_TYPES = {"MATERIAL", "COMMENT", "MARKET_ITEM", "USER"}


class ReportService:
    def __init__(
        self,
        read_repo: ReadApiRepository,
        auth_repo: AuthRepository,
        material_repo: MaterialRepository,
        comment_repo: CommentRepository,
        market_repo: MarketRepository,
        community_repo: CommunityRepository,
    ) -> None:
        self.read_repo = read_repo
        self.auth_repo = auth_repo
        self.material_repo = material_repo
        self.comment_repo = comment_repo
        self.market_repo = market_repo
        self.community_repo = community_repo

    def submit(self, session: Session, reporter_id: int, payload: ReportCreatePayload) -> dict[str, int]:
        entity = self.submit_report(
            session,
            reporter_id=reporter_id,
            target_type=payload.targetType,
            target_id=payload.targetId,
            reason=payload.reason,
        )
        return {"id": entity.id}

    def submit_report(self, session: Session, *, reporter_id: int, target_type: str, target_id: int, reason: str) -> ReportRecord:
        self._bootstrap(session)
        reporter = self.auth_repo.find_user_by_id(session, reporter_id)
        if reporter is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        normalized_target_type = self._normalize_target_type(target_type)
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请填写举报理由")
        self._ensure_target_exists(session, normalized_target_type, target_id, reporter_id)
        if self._exists_duplicate(normalized_target_type, target_id, reporter_id, session):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已提交过举报")
        entity = ReportRecord(
            target_type=normalized_target_type,
            target_id=target_id,
            reporter_id=reporter_id,
            reason=normalized_reason,
            status="PENDING",
        )
        self.community_repo.save_report(session, entity)
        active_count = self.community_repo.count_active_reports_for_target(
            session,
            target_type=normalized_target_type,
            target_id=target_id,
        )
        if active_count >= AUTO_HIDE_THRESHOLD:
            self._apply_auto_hide(session, normalized_target_type, target_id)
        session.commit()
        return entity

    def list_for_admin(self, session: Session, *, status_value: str | None, target_type: str | None, page: int, size: int) -> dict[str, Any]:
        self._bootstrap(session)
        normalized_status = self._normalize_status(status_value) if status_value else None
        normalized_target_type = self._normalize_target_type(target_type) if target_type else None
        safe_page = max(page, 0)
        safe_size = max(1, min(size, 100))
        total = self.community_repo.count_reports_for_admin(
            session,
            status_value=normalized_status,
            target_type=normalized_target_type,
        )
        items = self.community_repo.list_reports_for_admin(
            session,
            status_value=normalized_status,
            target_type=normalized_target_type,
            limit=safe_size,
            offset=safe_page * safe_size,
        )
        lookups = self._build_report_lookups(session, items)
        return {
            "items": [self._to_admin_item(session, item, lookups=lookups) for item in items],
            "meta": {"page": safe_page, "size": safe_size, "total": total},
        }

    def update_report(self, session: Session, report_id: int, payload: AdminReportUpdatePayload) -> dict[str, Any]:
        self._bootstrap(session)
        entity = self.community_repo.get_report(session, report_id)
        if entity is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="举报不存在")
        if payload.status:
            entity.status = self._normalize_status(payload.status)
        if payload.adminNote is not None:
            normalized_note = payload.adminNote.strip()
            entity.admin_note = normalized_note or None
        if payload.restoreTarget:
            self._restore_target(session, entity.target_type, entity.target_id)
        self.community_repo.save_report(session, entity)
        session.commit()
        return self._to_admin_item(session, entity)

    def _bootstrap(self, session: Session) -> None:
        seed = self.read_repo.load_seed()
        self.material_repo.ensure_seed_bootstrap(session, seed)
        self.comment_repo.ensure_seed_bootstrap(session, seed)
        self.market_repo.ensure_seed_bootstrap(session, seed)

    def _exists_duplicate(self, target_type: str, target_id: int, reporter_id: int, session: Session) -> bool:
        return self.community_repo.report_exists_for_target(
            session,
            target_type=target_type,
            target_id=target_id,
            reporter_id=reporter_id,
        )

    def _normalize_target_type(self, raw: str) -> str:
        normalized = raw.strip().upper()
        if normalized not in TARGET_TYPES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="举报类型无效")
        return normalized

    def _normalize_status(self, raw: str) -> str:
        normalized = raw.strip().upper()
        if normalized not in REPORT_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="举报状态无效")
        return normalized

    def _ensure_target_exists(self, session: Session, target_type: str, target_id: int, reporter_id: int) -> None:
        if target_type == "MATERIAL":
            if self.material_repo.get_material(session, target_id) is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")
            return
        if target_type == "COMMENT":
            if not self._comment_exists(session, target_id):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评论不存在")
            return
        if target_type == "MARKET_ITEM":
            if self.market_repo.get_item(session, target_id) is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品不存在")
            return
        target_user = self.auth_repo.find_user_by_id(session, target_id)
        if target_user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        if reporter_id == target_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能举报自己")

    def _apply_auto_hide(self, session: Session, target_type: str, target_id: int) -> None:
        if target_type == "MATERIAL":
            entity = self.material_repo.get_material(session, target_id)
            if entity is not None:
                entity.status = "HIDDEN"
                self.material_repo.save_material(session, entity)
            return
        if target_type == "COMMENT":
            session.execute(text("UPDATE comments SET status = 'hidden', updated_at = CURRENT_TIMESTAMP WHERE id = :target_id"), {"target_id": target_id})
            return
        if target_type == "MARKET_ITEM":
            entity = self.market_repo.get_item(session, target_id)
            if entity is not None and entity.status == "SALE":
                entity.status = "HIDDEN"
                self.market_repo.save_item(session, entity)
            return
        user = self.auth_repo.find_user_by_id(session, target_id)
        if user is not None:
            user.status = "hidden"
            self.auth_repo.save_user(session, user)

    def _restore_target(self, session: Session, target_type: str, target_id: int) -> None:
        if target_type == "MATERIAL":
            entity = self.material_repo.get_material(session, target_id)
            if entity is not None and entity.status == "HIDDEN":
                entity.status = "VISIBLE"
                self.material_repo.save_material(session, entity)
            return
        if target_type == "COMMENT":
            session.execute(
                text(
                    """
                    UPDATE comments
                    SET status = 'visible',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :target_id AND status = 'hidden'
                    """
                ),
                {"target_id": target_id},
            )
            return
        if target_type == "MARKET_ITEM":
            entity = self.market_repo.get_item(session, target_id)
            if entity is not None and entity.status == "HIDDEN":
                entity.status = "SALE"
                self.market_repo.save_item(session, entity)
            return
        user = self.auth_repo.find_user_by_id(session, target_id)
        if user is not None and user.status == "hidden":
            user.status = "active"
            self.auth_repo.save_user(session, user)

    def _build_report_lookups(self, session: Session, items: list[ReportRecord]) -> dict[str, dict[int, Any]]:
        lookups = {
            "users": self._load_users_by_id(
                session,
                [
                    *[int(item.reporter_id) for item in items],
                    *[int(item.target_id) for item in items if item.target_type == "USER"],
                ],
            ),
            "materials": self._load_records_by_id(self.material_repo, "list_materials_by_ids", session, [int(item.target_id) for item in items if item.target_type == "MATERIAL"]),
            "comments": self._load_records_by_id(self.comment_repo, "list_comments_by_ids", session, [int(item.target_id) for item in items if item.target_type == "COMMENT"]),
            "market_items": self._load_records_by_id(self.market_repo, "list_items_by_ids", session, [int(item.target_id) for item in items if item.target_type == "MARKET_ITEM"]),
        }
        return lookups

    def _load_users_by_id(self, session: Session, user_ids: list[int]) -> dict[int, Any]:
        ids = sorted(set(user_ids))
        if not ids:
            return {}
        loader = getattr(self.auth_repo, "find_users_by_ids", None)
        if not callable(loader):
            return {}
        return {int(user.id): user for user in loader(session, ids)}

    def _load_records_by_id(self, repo, method_name: str, session: Session, record_ids: list[int]) -> dict[int, Any]:
        ids = sorted(set(record_ids))
        if not ids:
            return {}
        loader = getattr(repo, method_name, None)
        if not callable(loader):
            return {}
        return {int(item.id): item for item in loader(session, ids)}

    def _comment_exists(self, session: Session, comment_id: int) -> bool:
        row = session.execute(
            text(
                """
                SELECT 1
                FROM comments
                WHERE id = :comment_id
                LIMIT 1
                """
            ),
            {"comment_id": comment_id},
        ).first()
        return row is not None

    def _to_admin_item(self, session: Session, entity: ReportRecord, *, lookups: dict[str, dict[int, Any]] | None = None) -> dict[str, Any]:
        target_label, target_status, target_url = self._resolve_target_info(session, entity.target_type, entity.target_id, lookups=lookups)
        reporter = (lookups or {}).get("users", {}).get(int(entity.reporter_id))
        if reporter is None:
            reporter = self.auth_repo.find_user_by_id(session, entity.reporter_id)
        reporter_name = (reporter.nickname or reporter.username) if reporter is not None else None
        return {
            "id": entity.id,
            "targetType": entity.target_type,
            "targetId": entity.target_id,
            "targetLabel": target_label,
            "targetStatus": target_status,
            "targetUrl": target_url,
            "reporterId": entity.reporter_id,
            "reporterName": reporter_name,
            "reason": entity.reason,
            "status": entity.status,
            "adminNote": entity.admin_note,
            "createdAt": serialize_datetime(entity.created_at),
        }

    def _resolve_target_info(
        self,
        session: Session,
        target_type: str,
        target_id: int,
        *,
        lookups: dict[str, dict[int, Any]] | None = None,
    ) -> tuple[str | None, str | None, str | None]:
        if target_type == "MATERIAL":
            entity = (lookups or {}).get("materials", {}).get(int(target_id))
            if entity is None:
                entity = self.material_repo.get_material(session, target_id)
            if entity is None:
                return "资料已删除", None, None
            return entity.title, entity.status, f"/materials/{entity.id}"
        if target_type == "COMMENT":
            entity = (lookups or {}).get("comments", {}).get(int(target_id))
            if entity is None:
                entity = self.comment_repo.get_comment(session, target_id)
            if entity is None:
                return "评论已删除", None, None
            label = (entity.content or "评论内容为空").strip() or "评论内容为空"
            if len(label) > 64:
                label = f"{label[:64]}..."
            return label, entity.status, f"/materials/{entity.material_id}#comment-{entity.id}"
        if target_type == "MARKET_ITEM":
            entity = (lookups or {}).get("market_items", {}).get(int(target_id))
            if entity is None:
                entity = self.market_repo.get_item(session, target_id)
            if entity is None:
                return "商品已删除", None, None
            return entity.title, entity.status, f"/market/{entity.id}"
        entity = (lookups or {}).get("users", {}).get(int(target_id))
        if entity is None:
            entity = self.auth_repo.find_user_by_id(session, target_id)
        if entity is None:
            return "用户已删除", None, None
        return entity.nickname or entity.username, entity.status, f"/u/{entity.id}"
