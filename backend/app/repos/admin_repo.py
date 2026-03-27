from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.admin import UserNoteRecord


class AdminRepository:
    def get_note(self, session: Session, note_id: int) -> UserNoteRecord | None:
        return session.get(UserNoteRecord, note_id)

    def save_note(self, session: Session, entity: UserNoteRecord) -> UserNoteRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def list_notes_by_user(self, session: Session, user_id: int) -> list[UserNoteRecord]:
        stmt = select(UserNoteRecord).where(UserNoteRecord.user_id == user_id).order_by(UserNoteRecord.created_at.desc(), UserNoteRecord.id.desc())
        return list(session.scalars(stmt))
