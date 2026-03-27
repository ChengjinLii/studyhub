from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


class SystemRepository:
    def ping(self, session: Session) -> bool:
        session.execute(text("SELECT 1"))
        return True
