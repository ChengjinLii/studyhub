from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, inspect, or_, select, text
from sqlalchemy.orm import Session

from app.models.community import FeedbackRecord, NotificationRecord, ReportRecord, VolunteerApplicationRecord


_TABLE_COLUMN_CACHE: dict[tuple[str, str], set[str]] = {}


def _bind_cache_key(session: Session) -> str:
    bind = session.get_bind()
    try:
        url = bind.engine.url
        rendered = url.render_as_string(hide_password=True)
        if url.database in {None, ":memory:"}:
            return f"{rendered}:{id(bind)}"
        return rendered
    except Exception:
        return str(bind)


def _table_columns(session: Session, table_name: str) -> set[str]:
    cache_key = (_bind_cache_key(session), table_name)
    cached = _TABLE_COLUMN_CACHE.get(cache_key)
    if cached is not None:
        return cached
    inspector = inspect(session.get_bind())
    column_names = {column["name"] for column in inspector.get_columns(table_name)}
    _TABLE_COLUMN_CACHE[cache_key] = column_names
    return column_names


def _has_table_column(session: Session, table_name: str, column_name: str) -> bool:
    return column_name in _table_columns(session, table_name)


class CommunityRepository:
    def save_feedback(self, session: Session, entity: FeedbackRecord) -> FeedbackRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def get_feedback(self, session: Session, feedback_id: int) -> FeedbackRecord | None:
        return session.get(FeedbackRecord, feedback_id)

    def list_feedbacks(self, session: Session) -> list[FeedbackRecord]:
        stmt = select(FeedbackRecord).order_by(FeedbackRecord.created_at.desc(), FeedbackRecord.id.desc())
        return list(session.scalars(stmt))

    def list_feedbacks_for_admin(
        self,
        session: Session,
        *,
        type_value: str | None,
        status_value: str | None,
    ) -> list[FeedbackRecord]:
        stmt = (
            select(FeedbackRecord)
            .where(*self._feedback_admin_filters(type_value=type_value, status_value=status_value))
            .order_by(FeedbackRecord.created_at.desc(), FeedbackRecord.id.desc())
        )
        return list(session.scalars(stmt))

    def save_volunteer(self, session: Session, entity: VolunteerApplicationRecord) -> VolunteerApplicationRecord:
        if self._uses_legacy_volunteers(session):
            timestamp = datetime.now(UTC)
            if entity.id is not None and session.execute(text("SELECT 1 FROM volunteer_applications WHERE id = :id LIMIT 1"), {"id": int(entity.id)}).first():
                session.execute(
                    text(
                        """
                        UPDATE volunteer_applications
                        SET user_id = :user_id,
                            name = :name,
                            school_major_grade = :school_major_grade,
                            skills = :skills,
                            time_commitment = :time_commitment,
                            portfolio_url = :portfolio_url,
                            intro = :intro,
                            contact = :contact,
                            status = :status,
                            updated_at = :updated_at
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": int(entity.id),
                        "user_id": entity.user_id,
                        "name": entity.name,
                        "school_major_grade": entity.school_major_grade,
                        "skills": entity.skills_csv,
                        "time_commitment": entity.time_commitment,
                        "portfolio_url": entity.portfolio_url,
                        "intro": entity.intro,
                        "contact": entity.contact,
                        "status": entity.status,
                        "updated_at": timestamp,
                    },
                )
                entity.updated_at = timestamp
                return entity
            result = session.execute(
                text(
                    """
                    INSERT INTO volunteer_applications (
                        user_id, name, school_major_grade, skills, time_commitment,
                        portfolio_url, intro, contact, status, created_at, updated_at
                    )
                    VALUES (
                        :user_id, :name, :school_major_grade, :skills, :time_commitment,
                        :portfolio_url, :intro, :contact, :status, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "user_id": entity.user_id,
                    "name": entity.name,
                    "school_major_grade": entity.school_major_grade,
                    "skills": entity.skills_csv,
                    "time_commitment": entity.time_commitment,
                    "portfolio_url": entity.portfolio_url,
                    "intro": entity.intro,
                    "contact": entity.contact,
                    "status": entity.status,
                    "created_at": entity.created_at or timestamp,
                    "updated_at": timestamp,
                },
            )
            if entity.id is None and result.lastrowid is not None:
                entity.id = int(result.lastrowid)
            entity.updated_at = timestamp
            return entity
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def get_volunteer(self, session: Session, volunteer_id: int) -> VolunteerApplicationRecord | None:
        if self._uses_legacy_volunteers(session):
            row = session.execute(
                text(
                    """
                    SELECT id, user_id, name, school_major_grade, skills, time_commitment,
                           portfolio_url, intro, contact, status, created_at, updated_at
                    FROM volunteer_applications
                    WHERE id = :volunteer_id
                    LIMIT 1
                    """
                ),
                {"volunteer_id": volunteer_id},
            ).mappings().first()
            return self._legacy_volunteer_record(row) if row is not None else None
        return session.get(VolunteerApplicationRecord, volunteer_id)

    def list_volunteers(self, session: Session) -> list[VolunteerApplicationRecord]:
        if self._uses_legacy_volunteers(session):
            rows = session.execute(
                text(
                    """
                    SELECT id, user_id, name, school_major_grade, skills, time_commitment,
                           portfolio_url, intro, contact, status, created_at, updated_at
                    FROM volunteer_applications
                    ORDER BY created_at DESC, id DESC
                    """
                )
            ).mappings().all()
            return [self._legacy_volunteer_record(row) for row in rows]
        stmt = select(VolunteerApplicationRecord).order_by(VolunteerApplicationRecord.created_at.desc(), VolunteerApplicationRecord.id.desc())
        return list(session.scalars(stmt))

    def list_volunteers_for_admin(self, session: Session, *, status_value: str | None) -> list[VolunteerApplicationRecord]:
        if self._uses_legacy_volunteers(session):
            where_sql = "WHERE status = :status" if status_value else ""
            params = {"status": status_value} if status_value else {}
            rows = session.execute(
                text(
                    f"""
                    SELECT id, user_id, name, school_major_grade, skills, time_commitment,
                           portfolio_url, intro, contact, status, created_at, updated_at
                    FROM volunteer_applications
                    {where_sql}
                    ORDER BY created_at DESC, id DESC
                    """
                ),
                params,
            ).mappings().all()
            return [self._legacy_volunteer_record(row) for row in rows]
        filters = (VolunteerApplicationRecord.status == status_value,) if status_value else ()
        stmt = (
            select(VolunteerApplicationRecord)
            .where(*filters)
            .order_by(VolunteerApplicationRecord.created_at.desc(), VolunteerApplicationRecord.id.desc())
        )
        return list(session.scalars(stmt))

    def save_notification(self, session: Session, entity: NotificationRecord) -> NotificationRecord:
        if self._uses_legacy_notifications(session):
            timestamp = datetime.now(UTC)
            result = session.execute(
                text(
                    """
                    INSERT INTO notifications (admin_id, user_id, message, created_at)
                    VALUES (:admin_id, :user_id, :message, :created_at)
                    """
                ),
                {
                    "admin_id": entity.admin_user_id,
                    "user_id": entity.user_id,
                    "message": entity.message,
                    "created_at": timestamp,
                },
            )
            notification_id = int(result.lastrowid) if result.lastrowid is not None else 0
            return NotificationRecord(
                id=notification_id or None,
                admin_user_id=entity.admin_user_id,
                user_id=entity.user_id,
                message=entity.message,
                created_at=timestamp,
                updated_at=timestamp,
            )
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def list_notifications(self, session: Session) -> list[NotificationRecord]:
        if self._uses_legacy_notifications(session):
            rows = session.execute(
                text(
                    """
                    SELECT id, admin_id, user_id, message, created_at
                    FROM notifications
                    ORDER BY created_at DESC, id DESC
                    """
                )
            ).mappings().all()
            return [self._legacy_notification_record(row) for row in rows]
        stmt = select(NotificationRecord).order_by(NotificationRecord.created_at.desc(), NotificationRecord.id.desc())
        return list(session.scalars(stmt))

    def list_notifications_for_user(self, session: Session, user_id: int, *, limit: int | None = None) -> list[NotificationRecord]:
        if self._uses_legacy_notifications(session):
            limit_sql = "LIMIT :limit" if limit is not None else ""
            params: dict[str, Any] = {"user_id": user_id}
            if limit is not None:
                params["limit"] = max(1, int(limit))
            rows = session.execute(
                text(
                    f"""
                    SELECT id, admin_id, user_id, message, created_at
                    FROM notifications
                    WHERE user_id IS NULL OR user_id = :user_id
                    ORDER BY created_at DESC, id DESC
                    {limit_sql}
                    """
                ),
                params,
            ).mappings().all()
            return [self._legacy_notification_record(row) for row in rows]
        stmt = (
            select(NotificationRecord)
            .where(or_(NotificationRecord.user_id.is_(None), NotificationRecord.user_id == user_id))
            .order_by(NotificationRecord.created_at.desc(), NotificationRecord.id.desc())
        )
        if limit is not None:
            stmt = stmt.limit(max(1, int(limit)))
        return list(session.scalars(stmt))

    def _uses_legacy_notifications(self, session: Session) -> bool:
        return _has_table_column(session, "notifications", "admin_id") and not _has_table_column(session, "notifications", "admin_user_id")

    def _uses_legacy_volunteers(self, session: Session) -> bool:
        return _has_table_column(session, "volunteer_applications", "skills") and not _has_table_column(session, "volunteer_applications", "skills_csv")

    def _legacy_volunteer_record(self, row) -> VolunteerApplicationRecord:
        return VolunteerApplicationRecord(
            id=int(row["id"]),
            user_id=None if row["user_id"] is None else int(row["user_id"]),
            name=row["name"],
            school_major_grade=row["school_major_grade"],
            skills_csv=row["skills"],
            time_commitment=row["time_commitment"],
            portfolio_url=row["portfolio_url"],
            intro=row["intro"],
            contact=row["contact"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"] or row["created_at"],
        )

    def _legacy_notification_record(self, row) -> NotificationRecord:
        return NotificationRecord(
            id=int(row["id"]),
            admin_user_id=None if row["admin_id"] is None else int(row["admin_id"]),
            user_id=None if row["user_id"] is None else int(row["user_id"]),
            message=row["message"],
            created_at=row["created_at"],
            updated_at=row["created_at"],
        )

    def save_report(self, session: Session, entity: ReportRecord) -> ReportRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def get_report(self, session: Session, report_id: int) -> ReportRecord | None:
        return session.get(ReportRecord, report_id)

    def list_reports(self, session: Session) -> list[ReportRecord]:
        stmt = select(ReportRecord).order_by(ReportRecord.created_at.desc(), ReportRecord.id.desc())
        return list(session.scalars(stmt))

    def report_exists_for_target(
        self,
        session: Session,
        *,
        target_type: str,
        target_id: int,
        reporter_id: int,
    ) -> bool:
        stmt = (
            select(1)
            .select_from(ReportRecord)
            .where(
                ReportRecord.target_type == target_type,
                ReportRecord.target_id == target_id,
                ReportRecord.reporter_id == reporter_id,
            )
            .limit(1)
        )
        return session.scalar(stmt) is not None

    def count_active_reports_for_target(
        self,
        session: Session,
        *,
        target_type: str,
        target_id: int,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(ReportRecord)
            .where(
                ReportRecord.target_type == target_type,
                ReportRecord.target_id == target_id,
                ReportRecord.status != "REJECTED",
            )
        )
        return int(session.scalar(stmt) or 0)

    def count_reports_for_admin(
        self,
        session: Session,
        *,
        status_value: str | None,
        target_type: str | None,
    ) -> int:
        stmt = select(func.count()).select_from(ReportRecord).where(
            *self._report_admin_filters(status_value=status_value, target_type=target_type)
        )
        return int(session.scalar(stmt) or 0)

    def list_reports_for_admin(
        self,
        session: Session,
        *,
        status_value: str | None,
        target_type: str | None,
        limit: int,
        offset: int,
    ) -> list[ReportRecord]:
        stmt = (
            select(ReportRecord)
            .where(*self._report_admin_filters(status_value=status_value, target_type=target_type))
            .order_by(ReportRecord.created_at.desc(), ReportRecord.id.desc())
            .limit(max(1, int(limit)))
            .offset(max(0, int(offset)))
        )
        return list(session.scalars(stmt))

    def _report_admin_filters(self, *, status_value: str | None, target_type: str | None):
        filters = []
        if status_value:
            filters.append(ReportRecord.status == status_value)
        if target_type:
            filters.append(ReportRecord.target_type == target_type)
        return tuple(filters)

    def _feedback_admin_filters(self, *, type_value: str | None, status_value: str | None):
        filters = []
        if type_value:
            filters.append(FeedbackRecord.type == type_value)
        if status_value:
            filters.append(FeedbackRecord.status == status_value)
        return tuple(filters)
