from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.models.admin import UserNoteRecord


class AdminRepository:
    def get_note(self, session: Session, note_id: int) -> UserNoteRecord | None:
        if _uses_legacy_user_notes(session):
            row = session.execute(
                text(
                    """
                    SELECT id, user_id, admin_id, message, created_at
                    FROM user_notes
                    WHERE id = :id
                    """
                ),
                {"id": note_id},
            ).mappings().first()
            return _user_note_from_legacy_row(row) if row is not None else None
        return session.get(UserNoteRecord, note_id)

    def save_note(self, session: Session, entity: UserNoteRecord) -> UserNoteRecord:
        if _uses_legacy_user_notes(session):
            created_at = entity.created_at or datetime.now(UTC)
            result = session.execute(
                text(
                    """
                    INSERT INTO user_notes (user_id, admin_id, message, created_at)
                    VALUES (:user_id, :admin_id, :message, :created_at)
                    """
                ),
                {
                    "user_id": entity.user_id,
                    "admin_id": entity.admin_user_id,
                    "message": entity.message,
                    "created_at": created_at,
                },
            )
            entity.id = int(result.lastrowid or 0)
            entity.created_at = created_at
            entity.updated_at = created_at
            return entity
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def list_notes_by_user(self, session: Session, user_id: int) -> list[UserNoteRecord]:
        if _uses_legacy_user_notes(session):
            rows = session.execute(
                text(
                    """
                    SELECT id, user_id, admin_id, message, created_at
                    FROM user_notes
                    WHERE user_id = :user_id
                    ORDER BY created_at DESC, id DESC
                    """
                ),
                {"user_id": user_id},
            ).mappings()
            return [_user_note_from_legacy_row(row) for row in rows]
        stmt = select(UserNoteRecord).where(UserNoteRecord.user_id == user_id).order_by(UserNoteRecord.created_at.desc(), UserNoteRecord.id.desc())
        return list(session.scalars(stmt))


def _uses_legacy_user_notes(session: Session) -> bool:
    return _has_table_column(session, "user_notes", "admin_id") and not _has_table_column(session, "user_notes", "admin_user_id")


def _user_note_from_legacy_row(row: Any) -> UserNoteRecord:
    created_at = _coerce_datetime(row["created_at"])
    return UserNoteRecord(
        id=int(row["id"]),
        user_id=int(row["user_id"]),
        admin_user_id=int(row["admin_id"]),
        message=str(row["message"]),
        created_at=created_at,
        updated_at=created_at,
    )


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(UTC)


def _has_table_column(session: Session, table: str, column: str) -> bool:
    bind = session.get_bind()
    try:
        return any(col["name"] == column for col in inspect(bind).get_columns(table))
    except Exception:
        return False
