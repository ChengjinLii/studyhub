from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.materials import MaterialRecord
from app.repos.material_repo import MaterialRepository
from app.services.materials_service import MaterialsService


class _DummyReadRepo:
    def load_seed(self):
        return {}


class _NoFullListMaterialRepo(MaterialRepository):
    def ensure_seed_bootstrap(self, session: Session, seed: dict) -> None:
        del session, seed

    def list_all_materials(self, session: Session):
        del session
        raise AssertionError("admin material list should not load all materials")


def _service() -> MaterialsService:
    return MaterialsService(
        settings=object(),  # type: ignore[arg-type]
        read_repo=_DummyReadRepo(),  # type: ignore[arg-type]
        auth_repo=None,  # type: ignore[arg-type]
        material_repo=_NoFullListMaterialRepo(),
        asset_store=None,  # type: ignore[arg-type]
    )


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    MaterialRecord.__table__.create(bind=engine)
    return Session(engine)


def _add_material(
    session: Session,
    *,
    material_id: int,
    title: str,
    status: str = "VISIBLE",
    created_at: datetime,
    deleted_at: datetime | None = None,
) -> None:
    session.add(
        MaterialRecord(
            id=material_id,
            source="local",
            title=title,
            price=0,
            is_free=True,
            general_course=False,
            tags_json="[]",
            delivery_method="FILE",
            preview_watermark_enabled=True,
            preview_source="AUTO",
            status=status,
            view_count=0,
            download_count=0,
            sales_count=0,
            like_count=0,
            comment_count=0,
            rating_avg=0.0,
            rating_count=0,
            created_at=created_at,
            updated_at=created_at,
            deleted_at=deleted_at,
        )
    )


def test_admin_material_list_filters_removed_before_pagination_without_loading_all_materials() -> None:
    service = _service()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    with _session() as session:
        for index in range(5):
            _add_material(
                session,
                material_id=100 + index,
                title=f"Removed {index}",
                status=" REMOVED ",
                created_at=base + timedelta(minutes=index),
                deleted_at=base + timedelta(minutes=index),
            )
        _add_material(session, material_id=10, title="Visible", created_at=base - timedelta(days=1))
        _add_material(session, material_id=9, title="Hidden", status="HIDDEN", created_at=base - timedelta(days=2))
        session.commit()

        data = service.list_for_admin(session, page=0, size=1, status_value=None)

    assert data["meta"] == {"page": 0, "size": 1, "total": 2}
    assert [item["id"] for item in data["items"]] == [10]


def test_admin_material_removed_filter_sorts_by_deleted_at_without_loading_all_materials() -> None:
    service = _service()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    with _session() as session:
        _add_material(session, material_id=1, title="Visible", created_at=base)
        _add_material(
            session,
            material_id=2,
            title="Older removed",
            status="REMOVED",
            created_at=base + timedelta(minutes=1),
            deleted_at=base + timedelta(days=1),
        )
        _add_material(
            session,
            material_id=3,
            title="Newer removed",
            status=" removed ",
            created_at=base + timedelta(minutes=2),
            deleted_at=base + timedelta(days=2),
        )
        session.commit()

        data = service.list_for_admin(session, page=0, size=20, status_value=" REMOVED ")

    assert data["meta"] == {"page": 0, "size": 20, "total": 2}
    assert [item["id"] for item in data["items"]] == [3, 2]
