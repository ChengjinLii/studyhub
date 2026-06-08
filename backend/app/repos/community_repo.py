from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.community import FeedbackRecord, NotificationRecord, ReportRecord, VolunteerApplicationRecord


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
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def get_volunteer(self, session: Session, volunteer_id: int) -> VolunteerApplicationRecord | None:
        return session.get(VolunteerApplicationRecord, volunteer_id)

    def list_volunteers(self, session: Session) -> list[VolunteerApplicationRecord]:
        stmt = select(VolunteerApplicationRecord).order_by(VolunteerApplicationRecord.created_at.desc(), VolunteerApplicationRecord.id.desc())
        return list(session.scalars(stmt))

    def list_volunteers_for_admin(self, session: Session, *, status_value: str | None) -> list[VolunteerApplicationRecord]:
        filters = (VolunteerApplicationRecord.status == status_value,) if status_value else ()
        stmt = (
            select(VolunteerApplicationRecord)
            .where(*filters)
            .order_by(VolunteerApplicationRecord.created_at.desc(), VolunteerApplicationRecord.id.desc())
        )
        return list(session.scalars(stmt))

    def save_notification(self, session: Session, entity: NotificationRecord) -> NotificationRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def list_notifications(self, session: Session) -> list[NotificationRecord]:
        stmt = select(NotificationRecord).order_by(NotificationRecord.created_at.desc(), NotificationRecord.id.desc())
        return list(session.scalars(stmt))

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
