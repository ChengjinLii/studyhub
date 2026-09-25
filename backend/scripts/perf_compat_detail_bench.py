#!/usr/bin/env python3
"""Benchmark the async-connection footprint of a logged-in material detail read.

Throwaway tooling for the 2026-09-26 API performance pass (see
backend/docs/perf/2026-09-26-api-performance.md).

get_detail_async's fan-out only happens when settings.requires_private_env_file
is true (preview/production), and that mode forbids SQLite outright (see
app/core/config_validation.py), and the compat SQL text() queries are written
against the real legacy MySQL column names, which don't match what
Base.metadata.create_all() produces on SQLite. So this script cannot run the
real compat SQL against a scratch SQLite database either.

Instead it stubs the individual loader methods (same technique as
tests/test_materials_compat_read.py) so each one still does one real,
trivial query (`SELECT 1`) against a small, explicitly pool-limited async
SQLite engine -- forcing a real connection checkout through SQLAlchemy's
pool for every call, with a configurable artificial delay to stand in for a
real network round trip to MySQL -- while returning canned data shaped like
a real row. That isolates exactly what changed: how many connections a
single logged-in detail request needs at once, independent of dataset
content.

It runs both the *old* fan-out-of-many-sessions shape (reconstructed here
from the pre-fix code, calling the same stubbed loaders through
service._call_with_new_async_session, which is unchanged and still used by
other methods) and the *new* single-shared-session shape
(service.get_detail_async) back to back, against the same constrained pool,
and reports peak concurrent connections + wall time for each.

Usage:
    .venv/bin/python backend/scripts/perf_compat_detail_bench.py \
        --concurrency 12 --pool-size 4 --max-overflow 2 --query-latency-ms 3
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--concurrency", type=int, default=12)
    parser.add_argument("--pool-size", type=int, default=4)
    parser.add_argument("--max-overflow", type=int, default=2)
    parser.add_argument("--query-latency-ms", type=float, default=3.0, help="simulated per-query round trip")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    asyncio.run(_run(args))


def _fake_row(material_id: int) -> dict:
    return {
        "id": material_id, "uploader_id": 1, "uploader_username": "owner", "uploader_nickname": "Owner",
        "title": "perf-bench material", "description": "d", "original_filename": "f.pdf", "file_type": "pdf",
        "file_key": "materials/perf-bench.pdf", "file_size": 1024, "price": 0, "is_free": 1,
        "school": "s", "college": "c", "major": "m",
        "is_general_education": 0, "netdisk_url": None, "netdisk_password": None, "netdisk_expired_at": None,
        "netdisk_reminder_at": None, "course_category": "MAJOR", "grade_type": "UG", "grade_value": "1",
        "preview_watermark_enabled": 1, "preview_source": "AUTO", "preview_manifest": None,
        "custom_preview_text": None, "custom_preview_images": "[]", "rating_avg": 0, "rating_count": 0,
        "like_count": 0, "view_count": 0, "download_count": 0, "sales_count": 0, "keywords": None,
        "status": "VISIBLE",
    }


async def _run(args: argparse.Namespace) -> None:
    from sqlalchemy import event, text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core import async_db
    from app.repos.material_repo import MaterialRepository
    from app.services.materials_service import MaterialsService

    # A file-based (not :memory:) sqlite URL is required to get a real
    # QueuePool that honors pool_size/max_overflow; :memory: always uses
    # SQLAlchemy's StaticPool (single shared connection), which doesn't
    # accept those kwargs and wouldn't let us model a bounded pool anyway.
    scratch_db = Path("/tmp/studyhub-perf-bench/compat-bench.sqlite3")
    scratch_db.parent.mkdir(parents=True, exist_ok=True)
    scratch_db.unlink(missing_ok=True)
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{scratch_db}",
        pool_size=args.pool_size,
        max_overflow=args.max_overflow,
        pool_timeout=5,
    )

    peak = {"value": 0}
    checked_out = {"value": 0}

    def on_checkout(*_a):
        checked_out["value"] += 1
        peak["value"] = max(peak["value"], checked_out["value"])

    def on_checkin(*_a):
        checked_out["value"] -= 1

    event.listen(engine.sync_engine, "checkout", on_checkout)
    event.listen(engine.sync_engine, "checkin", on_checkin)

    async_db._ASYNC_ENGINE = engine
    async_db._ASYNC_SESSION_FACTORY = None

    settings = SimpleNamespace(requires_private_env_file=True, async_read_db_enabled=True)
    fake_asset_store = SimpleNamespace(
        storage_provider=SimpleNamespace(build_signed_object_url=lambda **kw: None),
        build_public_custom_preview_url=lambda **kw: "/preview.png",
    )
    service = MaterialsService(settings, read_repo=None, auth_repo=None, material_repo=MaterialRepository(), asset_store=fake_asset_store)

    latency_s = args.query_latency_ms / 1000
    material_id, user_id = 100001, 1002
    row = _fake_row(material_id)

    async def touch(session) -> None:
        # Forces a real pool checkout, same as any real compat query would,
        # without depending on the materials table's real (legacy) schema.
        await session.execute(text("SELECT 1"))
        if latency_s:
            await asyncio.sleep(latency_s)

    async def fake_row(session, _material_id):
        await touch(session)
        return dict(row)

    async def fake_tags(session, _ids):
        await touch(session)
        return {material_id: ["真题"]}

    async def fake_counts(session, _ids):
        await touch(session)
        return {material_id: 5}

    async def fake_list(session, _material_id):
        await touch(session)
        return []

    async def fake_relation(session, _sql, _material_id, _user_id):
        await touch(session)
        return False

    async def fake_rating(session, _material_id, _user_id):
        await touch(session)
        return None

    async def fake_paid(session, _material_id, _user_id):
        await touch(session)
        return True

    async def fake_preview_urls(_material_id, _keys):
        return []

    service._compat_load_material_detail_row_async = fake_row
    service._compat_load_tags_map_async = fake_tags
    service._compat_load_comment_counts_async = fake_counts
    service._compat_load_versions_async = fake_list
    service._compat_load_reviews_async = fake_list
    service._compat_material_relation_exists_async = fake_relation
    service._compat_load_my_rating_async = fake_rating
    service._compat_has_paid_access_async = fake_paid
    service._compat_build_custom_preview_urls_async = fake_preview_urls

    async def old_style_get_detail() -> None:
        # Reconstructs the pre-fix fan-out: one _call_with_new_async_session
        # (== one async_session_scope(), i.e. one pool checkout) per loader,
        # all gathered concurrently. _call_with_new_async_session itself is
        # untouched by this change (list_materials_async etc. still use it).
        calls = [
            service._call_with_new_async_session(service._compat_load_material_detail_row_async, material_id),
            service._call_with_new_async_session(service._compat_load_tags_map_async, [material_id]),
            service._call_with_new_async_session(service._compat_load_comment_counts_async, [material_id]),
            service._call_with_new_async_session(service._compat_load_versions_async, material_id),
            service._call_with_new_async_session(service._compat_load_reviews_async, material_id),
            service._call_with_new_async_session(service._compat_material_relation_exists_async, "SELECT 1 FROM favorites", material_id, user_id),
            service._call_with_new_async_session(service._compat_material_relation_exists_async, "SELECT 1 FROM material_likes", material_id, user_id),
            service._call_with_new_async_session(service._compat_load_my_rating_async, material_id, user_id),
            service._call_with_new_async_session(service._compat_has_paid_access_async, material_id, user_id),
            service._compat_build_custom_preview_urls_async(material_id, []),
        ]
        await asyncio.gather(*calls)

    async def new_style_get_detail() -> None:
        await service.get_detail_async(session=None, current_user_id=user_id, material_id=material_id, can_manage_all=False)

    async def measure(label: str, coro_factory) -> None:
        peak["value"] = 0
        checked_out["value"] = 0
        errors = 0
        latencies: list[float] = []

        async def guarded():
            nonlocal errors
            started = time.perf_counter()
            try:
                await coro_factory()
                latencies.append((time.perf_counter() - started) * 1000)
            except Exception as exc:  # noqa: BLE001 - reporting, not handling
                errors += 1
                print(f"  error: {exc!r}")

        wall_started = time.perf_counter()
        await asyncio.gather(*(guarded() for _ in range(args.concurrency)))
        wall_ms = (time.perf_counter() - wall_started) * 1000

        print(f"[{label}] concurrency={args.concurrency} pool_size={args.pool_size} max_overflow={args.max_overflow} query_latency_ms={args.query_latency_ms}")
        print(f"  peak_concurrent_async_connections={peak['value']} (pool capacity={args.pool_size + args.max_overflow})")
        print(f"  errors={errors}")
        if latencies:
            ordered = sorted(latencies)
            print(f"  latency_ms mean={statistics.mean(ordered):.1f} p50={ordered[len(ordered)//2]:.1f} max={ordered[-1]:.1f}")
        print(f"  wall_ms={wall_ms:.1f}")

    await measure("old (one async session per loader)", old_style_get_detail)
    await measure("new (one shared async session)", new_style_get_detail)

    await engine.dispose()


if __name__ == "__main__":
    main()
