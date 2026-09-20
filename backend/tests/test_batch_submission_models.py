from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from app.models import Base, BatchAuditRecord, BatchPublicationRecord, BatchSubmissionItemRecord, BatchSubmissionRecord


MODELS = (BatchSubmissionRecord, BatchSubmissionItemRecord, BatchPublicationRecord, BatchAuditRecord)


def _migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0009_add_batch_submissions.py"
    spec = importlib.util.spec_from_file_location("batch_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("baseline", [False, True])
def test_migration_is_additive_repeatable_and_preserves_data(monkeypatch, baseline) -> None:
    engine = sa.create_engine("sqlite://")
    migration = _migration()
    assert migration.down_revision == "0008_material_submission_idempotency"
    with engine.begin() as conn:
        if baseline:
            Base.metadata.create_all(conn)
        conn.exec_driver_sql("CREATE TABLE existing_data (id INTEGER PRIMARY KEY, value TEXT)")
        conn.exec_driver_sql("INSERT INTO existing_data VALUES (1, 'unchanged')")
        before = set(sa.inspect(conn).get_table_names())
        monkeypatch.setattr(migration, "op", SimpleNamespace(get_bind=lambda: conn))
        migration.upgrade()
        batch = BatchSubmissionRecord.__table__
        conn.execute(batch.insert().values(
            uploader_id=1, submission_key="key", payload_digest="a" * 64,
            delivery_method="FILE", publication_intent="FREE",
        ))
        migration.upgrade()
        migration.downgrade()
        assert set(sa.inspect(conn).get_table_names()) == before | {model.__tablename__ for model in MODELS}
        assert conn.exec_driver_sql("SELECT * FROM existing_data").all() == [(1, "unchanged")]
        assert conn.scalar(sa.select(sa.func.count()).select_from(batch)) == 1
    engine.dispose()


def test_batch_model_defaults_nullability_and_unique_keys() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        for model in MODELS:
            model.__table__.create(conn)
        batch = BatchSubmissionRecord.__table__
        values = dict(submission_key="same", payload_digest="a" * 64, delivery_method="FILE", publication_intent="FREE")
        conn.execute(batch.insert().values(uploader_id=1, **values))
        conn.execute(batch.insert().values(uploader_id=2, **values))
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(batch.insert().values(uploader_id=1, **values))
        row = conn.execute(sa.select(batch).where(batch.c.uploader_id == 1)).mappings().one()
        assert row["status"] == "DRAFT"
        assert row["created_at"] is not None and row["updated_at"] is not None
        assert row["netdisk_password"] is None
        assert "password" not in batch.c

        item = BatchSubmissionItemRecord.__table__
        # Raw SQL tests database defaults as well as ORM defaults.
        conn.exec_driver_sql("INSERT INTO batch_submission_items (batch_id, name, size_bytes, content_type) VALUES (1, 'a.pdf', 1, 'application/pdf')")
        row = conn.execute(sa.select(item)).mappings().one()
        assert row["status"] == row["scan_status"] == "PENDING"
        assert row["scan_attempts"] == row["cleanup_attempts"] == 0
        for name in ("object_key", "reason", "claimed_at", "next_attempt_at", "upload_token_digest", "upload_token_expires_at", "upload_claimed_at"):
            assert row[name] is None

        publication = BatchPublicationRecord.__table__
        values = dict(publication_key="global-key", payload_digest="b" * 64, item_ids_json="[1]", operator_id=3)
        conn.execute(publication.insert().values(batch_id=1, **values))
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(publication.insert().values(batch_id=2, **values))
        row = conn.execute(sa.select(publication)).mappings().one()
        assert row["status"] == "PENDING" and row["material_id"] is None
        assert row["created_at"] is not None and row["updated_at"] is not None
        audit = BatchAuditRecord.__table__
        conn.execute(audit.insert().values(batch_id=1, operator_id=3, action="CREATE", detail="{}"))
        row = conn.execute(sa.select(audit)).mappings().one()
        assert row["created_at"] is not None and row["updated_at"] is not None
    engine.dispose()
