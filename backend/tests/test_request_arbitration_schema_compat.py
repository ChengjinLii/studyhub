from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.models.requests import RequestArbitrationRecord
from app.repos import request_repo as request_repo_module
from app.repos.request_repo import RequestRepository


def _create_legacy_request_schema():
    request_repo_module._TABLE_COLUMN_CACHE.clear()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE material_request_arbitrations (
                    id INTEGER PRIMARY KEY,
                    request_id INTEGER NOT NULL,
                    response_id INTEGER NOT NULL,
                    requester_id INTEGER NULL,
                    responder_id INTEGER NULL,
                    reason TEXT NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
                    admin_note TEXT NULL,
                    decided_by_user_id INTEGER NULL,
                    decided_at DATETIME NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
    return engine


def test_timed_out_arbitrations_tolerate_legacy_table_without_source_column() -> None:
    engine = _create_legacy_request_schema()
    created_at = datetime.now(UTC) - timedelta(days=3)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO material_request_arbitrations (
                    id, request_id, response_id, requester_id, responder_id, reason,
                    status, created_at, updated_at
                )
                VALUES (1, 10, 20, 7, 8, 'preview mismatch', 'PENDING', :created_at, :created_at)
                """
            ),
            {"created_at": created_at},
        )

    with Session(engine) as session:
        arbitrations = RequestRepository().list_timed_out_pending_arbitrations(
            session,
            datetime.now(UTC) - timedelta(days=2),
        )

    assert len(arbitrations) == 1
    assert arbitrations[0].source == "local"
    assert arbitrations[0].reason == "preview mismatch"


def test_save_arbitration_updates_legacy_table_without_source_column() -> None:
    engine = _create_legacy_request_schema()
    created_at = datetime.now(UTC) - timedelta(days=3)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO material_request_arbitrations (
                    id, request_id, response_id, requester_id, responder_id, reason,
                    status, created_at, updated_at
                )
                VALUES (1, 10, 20, 7, 8, 'preview mismatch', 'PENDING', :created_at, :created_at)
                """
            ),
            {"created_at": created_at},
        )

    repo = RequestRepository()
    with Session(engine) as session:
        arbitration = repo.get_arbitration(session, 1)
        assert arbitration is not None
        arbitration.status = "REFUNDING"
        repo.save_arbitration(session, arbitration)
        session.commit()

    with engine.connect() as connection:
        row = connection.execute(text("SELECT status FROM material_request_arbitrations WHERE id = 1")).mappings().one()
    assert row["status"] == "REFUNDING"


def test_save_arbitration_inserts_legacy_table_without_source_column() -> None:
    engine = _create_legacy_request_schema()
    repo = RequestRepository()
    with Session(engine) as session:
        saved = repo.save_arbitration(
            session,
            RequestArbitrationRecord(
                id=2,
                source="local",
                request_id=10,
                response_id=20,
                requester_id=7,
                responder_id=8,
                reason="auto dispute",
                status="PENDING",
            ),
        )
        assert saved.source == "local"
        session.commit()

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT request_id, response_id, reason, status FROM material_request_arbitrations WHERE id = 2")
        ).mappings().one()
    assert row == {"request_id": 10, "response_id": 20, "reason": "auto dispute", "status": "PENDING"}
