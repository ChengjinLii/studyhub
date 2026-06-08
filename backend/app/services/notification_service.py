from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.community import NotificationRecord
from app.repos.auth_repo import AuthRepository
from app.repos.community_repo import CommunityRepository
from app.repos.market_repo import MarketRepository
from app.schemas.notifications import NotificationCreatePayload
from app.services.read_support import serialize_datetime


class NotificationService:
    def __init__(self, auth_repo: AuthRepository, community_repo: CommunityRepository, market_repo: MarketRepository) -> None:
        self.auth_repo = auth_repo
        self.community_repo = community_repo
        self.market_repo = market_repo

    def create_notification(self, session: Session, *, admin_id: int, payload: NotificationCreatePayload) -> None:
        admin = self.auth_repo.find_user_by_id(session, admin_id)
        if admin is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="管理员不存在")
        if payload.userId is not None and self.auth_repo.find_user_by_id(session, payload.userId) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        entity = NotificationRecord(admin_user_id=admin.id, user_id=payload.userId, message=payload.message.strip())
        self.community_repo.save_notification(session, entity)
        session.commit()

    def get_summary(self, session: Session, user_id: int) -> dict[str, object]:
        user = self._require_user(session, user_id)
        notifications = self._visible_notifications(session, user_id, limit=1)
        latest_notification = notifications[0] if notifications else None
        market_events = self.market_repo.wants_for_seller(session, user_id)
        latest_market_event = market_events[0] if market_events else None

        latest_notification_time = latest_notification.created_at if latest_notification is not None else None
        latest_market_time = latest_market_event.created_at if latest_market_event is not None else None
        has_unread = self._is_newer(latest_notification_time, user.notification_read_at) or self._is_newer(latest_market_time, user.market_event_read_at)

        latest_message = None
        latest_sender = None
        if latest_market_time is not None and (latest_notification_time is None or latest_market_time >= latest_notification_time):
            latest_message = self._market_message(session, latest_market_event.item_id)
            latest_sender = "想要提醒"
        elif latest_notification is not None:
            latest_message = latest_notification.message
            latest_sender = self._resolve_sender(session, latest_notification.admin_user_id)

        return {"hasUnread": has_unread, "latestMessage": latest_message, "latestSender": latest_sender}

    def list_recent(self, session: Session, user_id: int) -> list[dict[str, object]]:
        self._require_user(session, user_id)
        base_items = [
            {
                "id": entity.id,
                "message": entity.message,
                "sender": self._resolve_sender(session, entity.admin_user_id),
                "createdAt": serialize_datetime(entity.created_at),
            }
            for entity in self._visible_notifications(session, user_id, limit=50)
        ]
        market_items = []
        for entity in self.market_repo.wants_for_seller(session, user_id)[:50]:
            market_items.append(
                {
                    "id": -entity.id,
                    "message": self._market_message(session, entity.item_id),
                    "sender": "想要提醒",
                    "createdAt": serialize_datetime(entity.created_at),
                }
            )
        combined = sorted(base_items + market_items, key=lambda item: item["createdAt"] or "", reverse=True)
        return combined[:50]

    def mark_all_read(self, session: Session, user_id: int) -> None:
        user = self._require_user(session, user_id)
        now = datetime.now(UTC)
        user.notification_read_at = now
        user.market_event_read_at = now
        self.auth_repo.save_user(session, user)
        session.commit()

    def _visible_notifications(self, session: Session, user_id: int, *, limit: int | None = None) -> list[NotificationRecord]:
        loader = getattr(self.community_repo, "list_notifications_for_user", None)
        if callable(loader):
            return loader(session, user_id, limit=limit)
        entities = self.community_repo.list_notifications(session)
        visible = [entity for entity in entities if entity.user_id is None or entity.user_id == user_id]
        return visible[:limit] if limit is not None else visible

    def _market_message(self, session: Session, item_id: int) -> str:
        item = self.market_repo.get_item(session, item_id)
        title = item.title if item is not None else "我的校园好物"
        want_count = item.want_count if item is not None else None
        count_text = str(want_count) if want_count is not None else "有人"
        return f"你的好物「{title}」有 {count_text} 人想要"

    def _resolve_sender(self, session: Session, admin_user_id: int | None) -> str | None:
        if admin_user_id is None:
            return None
        user = self.auth_repo.find_user_by_id(session, admin_user_id)
        if user is None:
            return "管理员"
        return user.nickname or user.username or "管理员"

    def _is_newer(self, candidate, read_at) -> bool:
        if candidate is None:
            return False
        if read_at is None:
            return True
        if candidate.tzinfo is None or read_at.tzinfo is None:
            return serialize_datetime(candidate) > serialize_datetime(read_at)
        return candidate > read_at

    def _require_user(self, session: Session, user_id: int):
        user = self.auth_repo.find_user_by_id(session, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        return user
