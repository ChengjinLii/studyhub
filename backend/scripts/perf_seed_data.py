#!/usr/bin/env python3
"""Seed a scratch SQLite database with synthetic data for API perf benchmarking.

This is throwaway tooling for the 2026-09-26 API performance pass (see
backend/docs/perf/2026-09-26-api-performance.md). It builds rows directly
with the app's SQLAlchemy models (bulk inserts, not the full service layer,
since the service layer does OSS/validation work that would make seeding
5k+ materials impractically slow) and writes them into a SQLite file that
must live under /tmp. It refuses to touch anything under a `.local-dev`
directory so it can never collide with a real local-dev database.

Usage:
    STUDYHUB_DATABASE_URL is set by this script itself; just run:
    .venv/bin/python backend/scripts/perf_seed_data.py /tmp/studyhub-perf-bench/db.sqlite3
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path

# The app ships a small static demo dataset (fixtures/runtime/read_api_seed.json)
# with ids like materials 101-104, market items 201-202, requests 401-402 and
# comments 9001-9101. Each list endpoint's `_bootstrap` re-checks on every
# request whether that demo data has been inserted yet (see e.g.
# MaterialRepository.ensure_seed_bootstrap), so synthetic ids that collide
# with the demo ids make that check never settle and redo real work on every
# request. Keep every synthetic id comfortably clear of the demo ranges.
USER_ID_BASE = 1000
MATERIAL_ID_BASE = 100_000
COMMENT_ID_BASE = 200_000
MARKET_ID_BASE = 100_000
REQUEST_ID_BASE = 100_000


def _configure_environment(db_path: Path) -> None:
    if ".local-dev" in db_path.parts:
        raise SystemExit("refusing to seed a .local-dev path")
    if not str(db_path).startswith(("/tmp/", "/private/tmp/")):
        raise SystemExit("seed target must live under /tmp")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    # Force (not setdefault): this script must never run against
    # preview/production settings, regardless of what's already in the
    # environment (e.g. a stray STUDYHUB_ENVIRONMENT=production from the
    # calling shell) -- requires_private_env_file mode also forbids SQLite
    # outright, so this would fail loudly rather than seed the wrong thing,
    # but don't rely on that.
    os.environ["STUDYHUB_ENVIRONMENT"] = "local-dev"
    os.environ["STUDYHUB_DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ.setdefault("STUDYHUB_LOCAL_DEV_ROOT_DIR", str(db_path.parent / "local-dev-root"))
    os.environ.setdefault("STUDYHUB_LOCAL_DEV_BOOTSTRAP_USER", "false")
    os.environ.setdefault("STUDYHUB_ACCESS_LOG_ENABLED", "true")
    os.environ.setdefault("STUDYHUB_LOG_FORMAT", "json")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: perf_seed_data.py <sqlite-path-under-tmp>")
    db_path = Path(sys.argv[1]).resolve()
    _configure_environment(db_path)

    # Imports happen after the environment is configured, since get_settings()
    # is cached on first use.
    from sqlalchemy.orm import Session

    from app.core.db import get_engine, initialize_database
    from app.models.auth import AuthUser
    from app.models.batch_submissions import (
        BatchPublicationRecord,
        BatchSubmissionItemRecord,
        BatchSubmissionRecord,
    )
    from app.models.comments import CommentRecord
    from app.models.market import MarketItemRecord
    from app.models.materials import MaterialRecord, MaterialViewRecord
    from app.models.requests import RequestRecord
    from app.repos.material_repo import MaterialRepository
    from app.repos.comment_repo import CommentRepository
    from app.repos.market_repo import MarketRepository
    from app.repos.request_repo import RequestRepository
    from app.repos.read_api_repo import ReadApiRepository
    from app.core.config import get_settings

    initialize_database()
    engine = get_engine()

    rng = random.Random(20260926)
    schools = [f"perf-school-{i}" for i in range(20)]
    colleges = [f"perf-college-{i}" for i in range(8)]
    majors = [f"perf-major-{i}" for i in range(30)]
    tags_pool = ["真题", "解析", "笔记", "课件", "习题", "期末", "复习", "重点", "汇总", "答案"]

    n_users = 200
    n_materials = int(os.environ.get("PERF_SEED_MATERIALS", "5000"))
    n_comments = int(os.environ.get("PERF_SEED_COMMENTS", "20000"))
    n_views = int(os.environ.get("PERF_SEED_VIEWS", "50000"))
    n_market_items = 300
    n_requests = 300
    n_batches = 60

    started = time.time()
    admin_user_id = USER_ID_BASE + 1
    with Session(engine) as session:
        users = [
            {
                "id": USER_ID_BASE + i,
                "username": f"perfuser{i}",
                "email": f"perfuser{i}@example.com",
                "password_hash": "not-a-real-hash",
                "nickname": f"用户{i}",
                "role_mask": 8 if USER_ID_BASE + i == admin_user_id else 1,  # perfuser1 is the load test's admin
                "verified": True,
                "free_download_quota": 200,
                "email_privacy": False,
                "status": "active",
                "school": rng.choice(schools),
                "college": rng.choice(colleges),
                "major": rng.choice(majors),
            }
            for i in range(1, n_users + 1)
        ]
        session.execute(AuthUser.__table__.insert(), users)
        session.commit()
        print(f"seeded {len(users)} users ({time.time() - started:.1f}s)")

        material_rows = []
        for i in range(1, n_materials + 1):
            material_rows.append(
                {
                    "id": MATERIAL_ID_BASE + i,
                    "source": "local",
                    "uploader_id": USER_ID_BASE + rng.randint(1, n_users),
                    "uploader_username": f"perfuser{rng.randint(1, n_users)}",
                    "uploader_nickname": "perf-uploader",
                    "title": f"资料 {i} 期末复习整理",
                    "description": "Synthetic perf-test material description. " * 3,
                    "original_filename": f"file-{i}.pdf",
                    "file_storage_key": f"materials/perf/{i}.pdf",
                    "file_type": "pdf",
                    "file_size": rng.randint(1024, 20_000_000),
                    "price": 0 if i % 3 == 0 else rng.randint(100, 2000),
                    "is_free": i % 3 == 0,
                    "school": rng.choice(schools),
                    "college": rng.choice(colleges),
                    "major": rng.choice(majors),
                    "general_course": i % 10 == 0,
                    "course_category": "GENERAL" if i % 10 == 0 else "MAJOR",
                    "grade_type": "UG",
                    "grade_value": str(rng.randint(1, 4)),
                    "tags_json": json.dumps(rng.sample(tags_pool, k=3), ensure_ascii=False),
                    "delivery_method": "FILE",
                    "preview_watermark_enabled": True,
                    "preview_source": "AUTO",
                    "status": "VISIBLE" if i % 500 != 0 else "HIDDEN",
                    "view_count": rng.randint(0, 5000),
                    "download_count": rng.randint(0, 500),
                    "sales_count": rng.randint(0, 50),
                    "like_count": rng.randint(0, 300),
                    "comment_count": 0,
                    "rating_avg": round(rng.uniform(3.0, 5.0), 1),
                    "rating_count": rng.randint(0, 80),
                }
            )
        session.execute(MaterialRecord.__table__.insert(), material_rows)
        session.commit()
        print(f"seeded {len(material_rows)} materials ({time.time() - started:.1f}s)")

        comment_rows = []
        for i in range(n_comments):
            comment_rows.append(
                {
                    "id": COMMENT_ID_BASE + i,
                    "source": "local",
                    "material_id": MATERIAL_ID_BASE + rng.randint(1, n_materials),
                    "parent_id": None,
                    "user_id": USER_ID_BASE + rng.randint(1, n_users),
                    "user_nickname": "perf-commenter",
                    "content": "Synthetic perf-test comment content.",
                    "like_count": rng.randint(0, 20),
                    "reply_count": 0,
                    "edited": False,
                    "status": "visible",
                }
            )
        session.execute(CommentRecord.__table__.insert(), comment_rows)
        session.commit()
        print(f"seeded {len(comment_rows)} comments ({time.time() - started:.1f}s)")

        view_rows = [
            {
                "material_id": MATERIAL_ID_BASE + rng.randint(1, n_materials),
                "user_id": USER_ID_BASE + rng.randint(1, n_users) if rng.random() < 0.5 else None,
                "viewer_token_hash": None if rng.random() < 0.5 else f"tok-{rng.randint(1, 200000)}",
            }
            for _ in range(n_views)
        ]
        session.execute(MaterialViewRecord.__table__.insert(), view_rows)
        session.commit()
        print(f"seeded {len(view_rows)} views ({time.time() - started:.1f}s)")

        market_rows = [
            {
                "id": MARKET_ID_BASE + i,
                "source": "local",
                "seller_id": USER_ID_BASE + rng.randint(1, n_users),
                "seller_name": "perf-seller",
                "title": f"市集商品 {i}",
                "description": "Synthetic perf-test market item.",
                "price_cents": rng.randint(100, 50000),
                "category": rng.choice(["BOOK", "ELECTRONICS", "OTHER"]),
                "want_count": rng.randint(0, 50),
                "school": rng.choice(schools),
                "status": "SALE",
            }
            for i in range(1, n_market_items + 1)
        ]
        session.execute(MarketItemRecord.__table__.insert(), market_rows)
        session.commit()

        request_rows = [
            {
                "id": REQUEST_ID_BASE + i,
                "source": "local",
                "requester_id": USER_ID_BASE + rng.randint(1, n_users),
                "requester_name": "perf-requester",
                "course": f"课程 {i}",
                "keyword": "复习资料",
                "school": rng.choice(schools),
                "college": rng.choice(colleges),
                "major": rng.choice(majors),
                "budget_cents": rng.randint(0, 5000),
                "funded_amount_cents": 0,
                "contribution_count": 0,
                "response_count": 0,
                "status": "OPEN",
            }
            for i in range(1, n_requests + 1)
        ]
        session.execute(RequestRecord.__table__.insert(), request_rows)
        session.commit()
        print(f"seeded {len(market_rows)} market items, {len(request_rows)} requests ({time.time() - started:.1f}s)")

        # Batch submissions: 60 batches x 3 items each, half already reviewed
        # with one published item, to exercise list_batches' items/publications
        # fan-out (see backend/app/services/batch_submission_service.py).
        for batch_index in range(1, n_batches + 1):
            batch = BatchSubmissionRecord(
                uploader_id=USER_ID_BASE + rng.randint(1, n_users),
                submission_key=f"perf-batch-{batch_index}",
                payload_digest=f"digest-{batch_index}",
                delivery_method="FILE",
                publication_intent="FREE",
                status="REVIEW",
            )
            session.add(batch)
            session.flush()
            items = []
            for item_index in range(3):
                item = BatchSubmissionItemRecord(
                    batch_id=batch.id,
                    name=f"item-{batch_index}-{item_index}.pdf",
                    size_bytes=rng.randint(1024, 2_000_000),
                    content_type="application/pdf",
                    object_key=f"batches/perf/{batch.id}/{item_index}.pdf",
                    status="UPLOADED",
                    scan_status="CLEAN",
                )
                session.add(item)
                items.append(item)
            if batch_index % 2 == 0:
                session.flush()
                material_id = MATERIAL_ID_BASE + rng.randint(1, n_materials)
                session.add(
                    BatchPublicationRecord(
                        batch_id=batch.id,
                        publication_key=f"perf-pub-{batch_index}",
                        material_id=material_id,
                        payload_digest=f"digest-{batch_index}",
                        item_ids_json=json.dumps([items[0].id]),
                        operator_id=admin_user_id,
                        status="PUBLISHED",
                    )
                )
        session.commit()
        print(f"seeded {n_batches} batch submissions ({time.time() - started:.1f}s)")

        # Run each domain's one-time demo-data bootstrap now, against an empty
        # (no collisions) low-id range, so it inserts the ~10 static demo rows
        # once and settles permanently instead of re-running its "is the demo
        # data present yet" check (and associated queries) on every request
        # for the rest of the benchmark.
        seed = ReadApiRepository(get_settings().resolved_read_api_seed_path).load_seed()
        MaterialRepository().ensure_seed_bootstrap(session, seed)
        CommentRepository().ensure_seed_bootstrap(session, seed)
        MarketRepository().ensure_seed_bootstrap(session, seed)
        RequestRepository().ensure_seed_bootstrap(session, seed)
        session.commit()
        print(f"ran one-time demo-data bootstrap ({time.time() - started:.1f}s)")

    print(f"done in {time.time() - started:.1f}s -> {db_path}")
    print(f"material id range: {MATERIAL_ID_BASE + 1}-{MATERIAL_ID_BASE + n_materials}")
    print(f"admin user id: {admin_user_id}, regular user id example: {USER_ID_BASE + 2}")


if __name__ == "__main__":
    main()
