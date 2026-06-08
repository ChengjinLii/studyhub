from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.market import MarketItemRecord
from app.services.market_service import MarketService


class _DummyReadRepo:
    def load_seed(self):
        return {}


class _NoFullListMarketRepo:
    def ensure_seed_bootstrap(self, session: Session, seed: dict) -> None:
        del session, seed

    def list_items(self, session: Session):
        del session
        raise AssertionError("admin market list should not load all items")


def _service() -> MarketService:
    return MarketService(
        settings=object(),  # type: ignore[arg-type]
        read_repo=_DummyReadRepo(),  # type: ignore[arg-type]
        auth_repo=None,  # type: ignore[arg-type]
        market_repo=_NoFullListMarketRepo(),  # type: ignore[arg-type]
        asset_store=None,  # type: ignore[arg-type]
    )


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    MarketItemRecord.__table__.create(bind=engine)
    return Session(engine)


def _add_item(
    session: Session,
    *,
    item_id: int,
    title: str,
    description: str,
    category: str = "BOOK",
    status: str = "SALE",
    created_at: datetime,
) -> None:
    session.add(
        MarketItemRecord(
            id=item_id,
            source="local",
            seller_id=1,
            seller_name="Alice",
            title=title,
            description=description,
            price_cents=100,
            category=category,
            images_json="[]",
            want_count=0,
            status=status,
            created_at=created_at,
            updated_at=created_at,
        )
    )


def test_admin_market_list_filters_before_pagination_without_loading_all_items() -> None:
    service = _service()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    with _session() as session:
        for index in range(5):
            _add_item(
                session,
                item_id=100 + index,
                title=f"Recent item {index}",
                description="普通商品",
                created_at=base + timedelta(minutes=index),
            )
        _add_item(session, item_id=10, title="Target router", description="target match", created_at=base - timedelta(days=1))
        _add_item(session, item_id=9, title="Target book", description="target match", created_at=base - timedelta(days=2))
        session.commit()

        data = service.list_for_admin(session, page=1, size=1, keyword="target", category=None, status_value=None)

    assert data["meta"] == {"page": 1, "size": 1, "total": 2}
    assert [item["id"] for item in data["items"]] == [10]


def test_admin_market_list_treats_like_wildcards_as_literal_keyword_text() -> None:
    service = _service()
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    with _session() as session:
        _add_item(session, item_id=1, title="Plain item", description="normal", created_at=created_at)
        _add_item(session, item_id=2, title="Percent % item", description="literal", created_at=created_at + timedelta(minutes=1))
        _add_item(session, item_id=3, title="Under_score item", description="literal", created_at=created_at + timedelta(minutes=2))
        session.commit()

        percent_data = service.list_for_admin(session, page=1, size=20, keyword="%", category=None, status_value=None)
        underscore_data = service.list_for_admin(session, page=1, size=20, keyword="_", category=None, status_value=None)

    assert [item["id"] for item in percent_data["items"]] == [2]
    assert [item["id"] for item in underscore_data["items"]] == [3]
