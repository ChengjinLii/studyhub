from __future__ import annotations

from sqlalchemy import select
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
