from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, close_all_sessions, sessionmaker

from app.core.config import get_settings


_ENGINE = None
_SESSION_FACTORY = None
LEGACY_TABLE_COMPATIBILITY: dict[str, tuple[str, ...]] = {
    "auth_users": ("users",),
    "material_favorites": ("favorites",),
    "material_reviews": ("reviews",),
    "material_purchases": ("orders",),
}
AGENTIC_DURABLE_TABLES = frozenset(
    {
        "agent_artifacts",
        "agent_jobs",
        "agent_outbox_events",
        "agent_runs",
        "agent_steps",
        "agent_threads",
        "agent_waits",
    }
)


def get_engine():
    global _ENGINE
    if _ENGINE is None:
        settings = get_settings()
        connect_args = {"check_same_thread": False} if settings.database_is_sqlite else {}
        engine_kwargs = {
            "future": True,
            "pool_pre_ping": True,
            "connect_args": connect_args,
            "echo": settings.database_echo,
        }
        if not settings.database_is_sqlite:
            engine_kwargs.update(
                {
                    "pool_size": settings.database_pool_size,
                    "max_overflow": settings.database_max_overflow,
                    "pool_timeout": settings.database_pool_timeout_seconds,
                    "pool_recycle": settings.database_pool_recycle_seconds,
                }
            )
        _ENGINE = create_engine(settings.resolved_database_url, **engine_kwargs)
    return _ENGINE


def get_session_factory():
    global _SESSION_FACTORY
    if _SESSION_FACTORY is None:
        _SESSION_FACTORY = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, future=True)
    return _SESSION_FACTORY


def get_db_session() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_database() -> None:
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))


def initialize_database() -> None:
    from app.models import Base

    Base.metadata.create_all(bind=get_engine())


def expected_table_names() -> list[str]:
    from app.models import Base

    return sorted(Base.metadata.tables.keys())


def required_table_names() -> list[str]:
    table_names = expected_table_names()
    if get_settings().agentic_durable_storage_enabled:
        return table_names
    return [name for name in table_names if name not in AGENTIC_DURABLE_TABLES]


def has_compatible_legacy_table(table_name: str, actual_tables: set[str]) -> bool:
    legacy_tables = LEGACY_TABLE_COMPATIBILITY.get(table_name)
    if not legacy_tables:
        return False
    return all(legacy_table in actual_tables for legacy_table in legacy_tables)


def list_missing_tables() -> list[str]:
    inspector = inspect(get_engine())
    actual_tables = set(inspector.get_table_names())
    return [
        name
        for name in required_table_names()
        if name not in actual_tables and not has_compatible_legacy_table(name, actual_tables)
    ]


def ensure_database_schema_ready() -> None:
    missing_tables = list_missing_tables()
    if missing_tables:
        preview = ", ".join(missing_tables[:8])
        suffix = "" if len(missing_tables) <= 8 else f" 等 {len(missing_tables)} 张表"
        raise RuntimeError(f"数据库 schema 不完整，缺少表：{preview}{suffix}")


def prepare_database_runtime() -> None:
    settings = get_settings()
    if settings.should_auto_create_database:
        initialize_database()
    check_database()
    if not settings.allows_partial_schema_compatibility:
        ensure_database_schema_ready()


def reset_database_runtime() -> None:
    global _ENGINE, _SESSION_FACTORY

    close_all_sessions()
    if _ENGINE is not None:
        _ENGINE.dispose()
    _ENGINE = None
    _SESSION_FACTORY = None


def recreate_database() -> None:
    from app.models import Base

    Base.metadata.drop_all(bind=get_engine())
    Base.metadata.create_all(bind=get_engine())
