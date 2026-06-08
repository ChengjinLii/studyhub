from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.community import FeedbackRecord, VolunteerApplicationRecord
from app.repos.community_repo import CommunityRepository
from app.schemas.community import FeedbackPayload, UpdateStatusPayload, VolunteerPayload
from app.services.read_support import serialize_datetime


FEEDBACK_TYPES = {"BUG", "FEATURE", "UX", "OTHER"}
FEEDBACK_STATUSES = {"NEW", "IN_PROGRESS", "RESOLVED", "IGNORED"}
VOLUNTEER_STATUSES = {"NEW", "CONTACTED", "ACCEPTED", "REJECTED"}


class CommunityService:
    def __init__(self, repo: CommunityRepository) -> None:
        self.repo = repo

    def submit_feedback(self, session: Session, payload: FeedbackPayload, user_id: int | None) -> dict[str, Any]:
        entity = FeedbackRecord(
            user_id=user_id,
            type=self._normalize_feedback_type(payload.type),
            page=self._strip(payload.page),
            content=payload.content.strip(),
            contact=self._strip(payload.contact),
        )
        self.repo.save_feedback(session, entity)
        session.commit()
        return self._to_feedback(entity)

    def submit_volunteer(self, session: Session, payload: VolunteerPayload, user_id: int | None) -> dict[str, Any]:
        entity = VolunteerApplicationRecord(
            user_id=user_id,
            name=payload.name.strip(),
            school_major_grade=payload.schoolMajorGrade.strip(),
            skills_csv=self._join_skills(payload.skills),
            time_commitment=self._strip(payload.timeCommitment),
            portfolio_url=self._strip(payload.portfolioUrl),
            intro=payload.intro.strip(),
            contact=self._strip(payload.contact),
        )
        self.repo.save_volunteer(session, entity)
        session.commit()
        return self._to_volunteer(entity)

    def list_feedbacks(self, session: Session, type_value: str | None, status_value: str | None) -> list[dict[str, Any]]:
        normalized_type = self._normalize_feedback_type(type_value) if type_value else None
        normalized_status = self._normalize_feedback_status(status_value) if status_value else None
        items = self.repo.list_feedbacks_for_admin(
            session,
            type_value=normalized_type,
            status_value=normalized_status,
        )
        return [self._to_feedback(item) for item in items]

    def update_feedback_status(self, session: Session, feedback_id: int, payload: UpdateStatusPayload) -> dict[str, Any]:
        entity = self.repo.get_feedback(session, feedback_id)
        if entity is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="反馈不存在")
        entity.status = self._normalize_feedback_status(payload.status)
        self.repo.save_feedback(session, entity)
        session.commit()
        return self._to_feedback(entity)

    def list_volunteers(self, session: Session, status_value: str | None) -> list[dict[str, Any]]:
        normalized_status = self._normalize_volunteer_status(status_value) if status_value else None
        items = self.repo.list_volunteers_for_admin(session, status_value=normalized_status)
        return [self._to_volunteer(item) for item in items]

    def update_volunteer_status(self, session: Session, volunteer_id: int, payload: UpdateStatusPayload) -> dict[str, Any]:
        entity = self.repo.get_volunteer(session, volunteer_id)
        if entity is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="申请不存在")
        entity.status = self._normalize_volunteer_status(payload.status)
        self.repo.save_volunteer(session, entity)
        session.commit()
        return self._to_volunteer(entity)

    def _normalize_feedback_type(self, raw: str) -> str:
        normalized = raw.strip().upper()
        if normalized not in FEEDBACK_TYPES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="反馈类型仅支持 BUG/FEATURE/UX/OTHER")
        return normalized

    def _normalize_feedback_status(self, raw: str) -> str:
        normalized = raw.strip().upper()
        if normalized not in FEEDBACK_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="反馈状态仅支持 NEW/IN_PROGRESS/RESOLVED/IGNORED")
        return normalized

    def _normalize_volunteer_status(self, raw: str) -> str:
        normalized = raw.strip().upper()
        if normalized not in VOLUNTEER_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="申请状态仅支持 NEW/CONTACTED/ACCEPTED/REJECTED")
        return normalized

    def _join_skills(self, skills: list[str] | None) -> str | None:
        if not skills:
            return None
        values: list[str] = []
        seen: set[str] = set()
        for item in skills:
            normalized = item.strip().upper()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            values.append(normalized)
        return ",".join(values) if values else None

    def _strip(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    def _to_feedback(self, entity: FeedbackRecord) -> dict[str, Any]:
        return {
            "id": entity.id,
            "userId": entity.user_id,
            "type": entity.type,
            "page": entity.page,
            "content": entity.content,
            "contact": entity.contact,
            "status": entity.status,
            "createdAt": serialize_datetime(entity.created_at),
            "updatedAt": serialize_datetime(entity.updated_at),
        }

    def _to_volunteer(self, entity: VolunteerApplicationRecord) -> dict[str, Any]:
        skills = [item for item in (part.strip() for part in (entity.skills_csv or "").split(",")) if item]
        return {
            "id": entity.id,
            "userId": entity.user_id,
            "name": entity.name,
            "schoolMajorGrade": entity.school_major_grade,
            "skills": skills,
            "timeCommitment": entity.time_commitment,
            "portfolioUrl": entity.portfolio_url,
            "intro": entity.intro,
            "contact": entity.contact,
            "status": entity.status,
            "createdAt": serialize_datetime(entity.created_at),
            "updatedAt": serialize_datetime(entity.updated_at),
        }
