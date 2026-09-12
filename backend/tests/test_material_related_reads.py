from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session

from app.services.materials_compat import MaterialsCompatMixin


@pytest.fixture
def related_database(tmp_path):
    path = tmp_path / "related.sqlite"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        for ddl in (
            "CREATE TABLE material_tags (id INTEGER, material_id INTEGER, tag TEXT)",
            "CREATE TABLE comments (material_id INTEGER, status TEXT)",
            "CREATE TABLE material_versions (id INTEGER, material_id INTEGER, version_label TEXT, changelog TEXT, file_type TEXT, created_at TEXT)",
            "CREATE TABLE reviews (id INTEGER, material_id INTEGER, reviewer TEXT, rating TEXT, comment TEXT, created_at TEXT)",
        ):
            connection.execute(text(ddl))
        connection.execute(text("INSERT INTO material_tags VALUES (3,1,'second'),(1,1,'first'),(2,1,'  '),(4,1,'first'),(5,2,NULL),(6,3,'other')"))
        connection.execute(text("INSERT INTO comments VALUES (1,'visible'),(1,'visible'),(1,'hidden'),(2,'VISIBLE'),(3,'visible')"))
        connection.execute(text("INSERT INTO material_versions VALUES (1,1,'v1',NULL,'PDF','2026-01-01'),(2,1,'v2','changes','DOCX','2026-01-01'),(3,2,'other',NULL,NULL,NULL)"))
        connection.execute(text("INSERT INTO reviews VALUES (1,1,'A','bad',NULL,NULL),(2,1,'B','4','review','2026-01-02'),(3,2,'C','5','other','2026-01-03')"))
    yield path, engine
    engine.dispose()


CASES = [
    ("tags_map", [1, 2], {1: ["first", "second", "first"], 2: []}),
    ("comment_counts", [1, 2], {1: 2}),
    ("versions", 1, [
        {"id": 2, "versionLabel": "v2", "changelog": "changes", "fileType": "DOCX", "createdAt": "2026-01-01T00:00:00Z"},
        {"id": 1, "versionLabel": "v1", "changelog": None, "fileType": "PDF", "createdAt": "2026-01-01T00:00:00Z"},
    ]),
    ("reviews", 1, [
        {"id": 2, "reviewer": "B", "rating": 4, "comment": "review", "createdAt": "2026-01-02T00:00:00Z"},
        {"id": 1, "reviewer": "A", "rating": 0, "comment": None, "createdAt": None},
    ]),
    ("tags_map", [], {}),
    ("comment_counts", [], {}),
    ("versions", 999, []),
    ("reviews", 999, []),
]


@pytest.mark.parametrize("name,argument,expected", CASES)
def test_sync_and_async_related_reads_preserve_results_and_sql(related_database, name, argument, expected):
    path, engine = related_database
    service = MaterialsCompatMixin()
    sync_sql = []
    async_sql = []

    def capture_sync(_connection, _cursor, statement, parameters, _context, _many):
        sync_sql.append((" ".join(statement.split()), parameters))

    event.listen(engine, "before_cursor_execute", capture_sync)
    with Session(engine) as session:
        actual = getattr(service, f"_compat_load_{name}")(session, argument)
        assert actual == expected
        assert not session.new and not session.dirty and not session.deleted

    async def read_async():
        async_engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

        def capture(_connection, _cursor, statement, parameters, _context, _many):
            async_sql.append((" ".join(statement.split()), parameters))

        event.listen(async_engine.sync_engine, "before_cursor_execute", capture)
        try:
            async with AsyncSession(async_engine) as session:
                assert await getattr(service, f"_compat_load_{name}_async")(session, argument) == expected
                assert not session.new and not session.dirty and not session.deleted
        finally:
            await async_engine.dispose()

    asyncio.run(read_async())
    assert sync_sql == async_sql
    assert len(sync_sql) == (0 if argument == [] else 1)
    assert all(sql.startswith("SELECT ") for sql, _ in sync_sql)
