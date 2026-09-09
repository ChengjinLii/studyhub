import asyncio
from types import SimpleNamespace

import pytest

from app.services.materials_service import MaterialsService


def make_service():
    return MaterialsService(
        SimpleNamespace(requires_private_env_file=True, async_read_db_enabled=True),
        None, None, None, None,
    )


@pytest.mark.parametrize("sort,needs_profile", [
    ("newest", False), ("downloads", False), ("recent_downloads", False),
    ("price", False), ("sales", False), ("latest", True), ("recommended", True),
])
def test_profile_reads_follow_existing_sort_semantics(sort, needs_profile):
    async def scenario():
        service = make_service()
        calls = []
        async def call(loader, *args, **kwargs):
            calls.append(loader.__name__)
            if loader.__name__ == "_compat_load_material_rows_async":
                assert (kwargs["profile"] is not None) == needs_profile
                return []
            if loader.__name__ == "_compat_count_material_rows_async":
                return 0
            if loader.__name__ == "_compat_load_available_tags_async":
                return []
            return {}
        service._call_with_new_async_session = call
        result = await service.list_materials_async(
            None, 42, keyword=None, school=None, college=None, major=None,
            tag=None, grade_value=None, course_category=None, price=None,
            sort=sort, page=1, size=24,
        )
        assert ("_compat_load_user_profile_async" in calls) == needs_profile
        assert result["meta"] == {"page": 1, "size": 24, "total": 0}
        assert result["items"] == []
        assert not service._summary_load_gates
    asyncio.run(scenario())


def test_summary_gate_rechecks_cache_before_loading_and_cleans_up():
    async def scenario():
        service = make_service()
        cached = None
        queries = 0
        async def loader():
            nonlocal cached, queries
            if cached is None:
                queries += 1
                await asyncio.sleep(.02)
                cached = {"count": 42}
            return cached
        async def call(fn):
            return await fn()
        service._call_with_new_async_session = call
        results = await asyncio.gather(*[service._call_summary_with_new_async_session(loader) for _ in range(8)])
        assert results == [{"count": 42}] * 8
        assert queries == 1
        assert not service._summary_load_gates
    asyncio.run(scenario())


def test_cancelled_summary_producer_releases_gate():
    async def scenario():
        service = make_service()
        entered = asyncio.Event()
        async def loader():
            entered.set()
            await asyncio.Event().wait()
        async def call(fn):
            return await fn()
        service._call_with_new_async_session = call
        task = asyncio.create_task(service._call_summary_with_new_async_session(loader))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not service._summary_load_gates
    asyncio.run(scenario())
