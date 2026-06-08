from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.models.market import MarketItemRecord
from app.repos import market_repo as market_repo_module
from app.repos.market_repo import MarketRepository
from app.services.market_service import MarketService


class _DummyReadRepo:
    def load_seed(self):
        return {}


class _DummyAuthRepo:
    def count_users(self, session: Session) -> int:
        del session
        return 0


def _legacy_session() -> Session:
    market_repo_module._TABLE_COLUMN_CACHE.clear()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    username TEXT NULL,
                    nickname TEXT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE market_items (
                    id INTEGER PRIMARY KEY,
                    seller_id INTEGER NULL,
                    title TEXT NOT NULL,
                    description TEXT NULL,
                    price INTEGER NOT NULL DEFAULT 0,
                    category TEXT NOT NULL DEFAULT 'OTHER',
                    images_json TEXT NULL,
                    contact_type TEXT NULL,
                    contact_value TEXT NULL,
                    want_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'SALE',
                    school TEXT NULL,
                    created_at DATETIME NULL,
                    updated_at DATETIME NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE market_wants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at DATETIME NULL
                )
                """
            )
        )
    return Session(engine)


def test_market_wants_for_seller_tolerates_missing_updated_at() -> None:
    repo = MarketRepository()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    with _legacy_session() as session:
        session.execute(text("INSERT INTO users (id, username, nickname) VALUES (1, 'seller', '卖家')"))
        session.execute(
            text(
                """
                INSERT INTO market_items (
                    id, seller_id, title, description, price, category, images_json,
                    want_count, status, school, created_at, updated_at
                )
                VALUES (10, 1, '教材', 'desc', 1234, 'BOOK', '[]', 2, 'SALE', 'UESTC', :created_at, :created_at)
                """
            ),
            {"created_at": base},
        )
        session.execute(
            text("INSERT INTO market_wants (item_id, user_id, created_at) VALUES (10, 7, :created_at)"),
            {"created_at": base + timedelta(minutes=1)},
        )
        session.commit()

        wants = repo.wants_for_seller(session, 1, limit=1)
        items = repo.list_items_by_ids(session, [10])

    assert [(want.item_id, want.user_id) for want in wants] == [(10, 7)]
    assert wants[0].updated_at == wants[0].created_at
    assert items[0].price_cents == 1234
    assert items[0].title == "教材"


def test_market_want_write_paths_tolerate_missing_updated_at() -> None:
    repo = MarketRepository()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    with _legacy_session() as session:
        session.execute(
            text(
                """
                INSERT INTO market_items (
                    id, seller_id, title, description, price, category, images_json,
                    want_count, status, school, created_at, updated_at
                )
                VALUES (10, 1, '教材', 'desc', 1234, 'BOOK', '[]', 0, 'SALE', 'UESTC', :created_at, :created_at)
                """
            ),
            {"created_at": base},
        )
        repo.add_want(session, item_id=10, user_id=7)
        session.commit()

        found = repo.find_want(session, 10, 7)
        assert found is not None

        repo.remove_want(session, found)
        session.commit()

        assert repo.find_want(session, 10, 7) is None


def test_legacy_market_item_save_updates_only_existing_columns() -> None:
    repo = MarketRepository()
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    with _legacy_session() as session:
        item = MarketItemRecord(
            id=20,
            source="local",
            seller_id=1,
            seller_name="卖家",
            title="计算器",
            description="desc",
            price_cents=8800,
            category="DIGITAL",
            images_json="[]",
            want_count=3,
            status="SALE",
            school="UESTC",
            contact_type="QQ",
            contact_value="123",
            created_at=created_at,
            updated_at=created_at,
        )

        repo.save_item(session, item)
        session.commit()

        item.want_count = 4
        item.status = "SOLD"
        repo.save_item(session, item)
        session.commit()

        row = session.execute(text("SELECT price, want_count, status FROM market_items WHERE id = 20")).mappings().one()

    assert dict(row) == {"price": 8800, "want_count": 4, "status": "SOLD"}


def test_admin_market_list_uses_legacy_schema_in_production_mode() -> None:
    service = MarketService(
        settings=SimpleNamespace(requires_private_env_file=True),  # type: ignore[arg-type]
        read_repo=_DummyReadRepo(),  # type: ignore[arg-type]
        auth_repo=_DummyAuthRepo(),  # type: ignore[arg-type]
        market_repo=MarketRepository(),
        asset_store=None,  # type: ignore[arg-type]
    )
    base = datetime(2026, 1, 1, tzinfo=UTC)
    with _legacy_session() as session:
        session.execute(text("INSERT INTO users (id, username, nickname) VALUES (1, 'seller', '卖家')"))
        session.execute(
            text(
                """
                INSERT INTO market_items (
                    id, seller_id, title, description, price, category, images_json,
                    contact_type, contact_value, want_count, status, school, created_at, updated_at
                )
                VALUES
                    (1, 1, '普通教材', 'math', 1200, 'BOOK', '[]', 'QQ', '123', 0, 'SALE', 'UESTC', :older, :older),
                    (2, 1, '目标计算器', 'target', 3400, 'DIGITAL', '[]', 'QQ', '123', 3, 'SOLD', 'UESTC', :newer, :newer)
                """
            ),
            {"older": base, "newer": base + timedelta(minutes=1)},
        )
        session.commit()

        data = service.list_for_admin(session, page=1, size=10, keyword="目标", category=None, status_value=None)

    assert data["meta"] == {"page": 1, "size": 10, "total": 1}
    assert data["items"][0]["id"] == 2
    assert data["items"][0]["price"] == 34.0
    assert data["items"][0]["sellerName"] == "卖家"
