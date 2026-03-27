from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


_ASYNC_ENGINE = None
_ASYNC_SESSION_FACTORY = None


def _to_async_database_url(database_url: str) -> str:
    if database_url.startswith("sqlite+pysqlite://"):
        return database_url.replace("sqlite+pysqlite://", "sqlite+aiosqlite://", 1)
    if database_url.startswith("sqlite:///"):
        return database_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if database_url.startswith("mysql+pymysql://"):
        return database_url.replace("mysql+pymysql://", "mysql+aiomysql://", 1)
    if database_url.startswith("mysql://"):
        return database_url.replace("mysql://", "mysql+aiomysql://", 1)
    return database_url


def get_async_engine():
    global _ASYNC_ENGINE
    if _ASYNC_ENGINE is None:
        settings = get_settings()
        database_url = _to_async_database_url(settings.resolved_database_url)
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        engine_kwargs = {
            "future": True,
            "pool_pre_ping": True,
            "connect_args": connect_args,
            "echo": settings.database_echo,
        }
        if not database_url.startswith("sqlite"):
            engine_kwargs.update(
                {
                    "pool_size": settings.database_pool_size,
                    "max_overflow": settings.database_max_overflow,
                    "pool_timeout": settings.database_pool_timeout_seconds,
                    "pool_recycle": settings.database_pool_recycle_seconds,
                }
            )
        _ASYNC_ENGINE = create_async_engine(database_url, **engine_kwargs)
    return _ASYNC_ENGINE


def get_async_session_factory():
    global _ASYNC_SESSION_FACTORY
    if _ASYNC_SESSION_FACTORY is None:
        _ASYNC_SESSION_FACTORY = async_sessionmaker(
            bind=get_async_engine(),
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
            class_=AsyncSession,
        )
    return _ASYNC_SESSION_FACTORY


@asynccontextmanager
async def async_session_scope() -> AsyncGenerator[AsyncSession, None]:
    session = get_async_session_factory()()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def reset_async_database_runtime() -> None:
    global _ASYNC_ENGINE, _ASYNC_SESSION_FACTORY

    if _ASYNC_ENGINE is not None:
        await _ASYNC_ENGINE.dispose()
    _ASYNC_ENGINE = None
    _ASYNC_SESSION_FACTORY = None
