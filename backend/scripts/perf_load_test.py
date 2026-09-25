#!/usr/bin/env python3
"""Async httpx load test for the hot public StudyHub API endpoints.

Throwaway tooling for the 2026-09-26 API performance pass (see
backend/docs/perf/2026-09-26-api-performance.md). Point it at a locally
running uvicorn instance (started against a seeded scratch SQLite database;
see perf_seed_data.py) and it reports p50/p95/p99 latency and throughput per
endpoint at a fixed concurrency.

Usage:
    .venv/bin/python backend/scripts/perf_load_test.py http://127.0.0.1:8931 \
        --requests 300 --concurrency 20 --materials 5000 --out /tmp/result.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass, field

# Must match backend/scripts/perf_seed_data.py's id ranges so the load test
# hits ids that actually exist (and stays clear of the app's static demo
# seed rows at low ids).
USER_ID_BASE = 1000
MATERIAL_ID_BASE = 100_000


@dataclass
class EndpointResult:
    name: str
    latencies_ms: list[float] = field(default_factory=list)
    statuses: dict[int, int] = field(default_factory=dict)
    errors: int = 0

    def summary(self, total_wall_seconds: float) -> dict[str, object]:
        if not self.latencies_ms:
            return {"name": self.name, "requests": 0, "errors": self.errors}
        ordered = sorted(self.latencies_ms)

        def pct(p: float) -> float:
            index = min(len(ordered) - 1, int(len(ordered) * p))
            return round(ordered[index], 2)

        return {
            "name": self.name,
            "requests": len(ordered),
            "errors": self.errors,
            "statuses": self.statuses,
            "p50_ms": pct(0.50),
            "p95_ms": pct(0.95),
            "p99_ms": pct(0.99),
            "mean_ms": round(statistics.mean(ordered), 2),
            "rps": round(len(ordered) / total_wall_seconds, 1) if total_wall_seconds > 0 else None,
        }


def _bearer_token(user_id: int, role_mask: int) -> str:
    # Mirrors tests/support.py:build_auth_headers so tokens are valid against
    # a server started with the same (default dev) STUDYHUB_JWT_SECRET.
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from app.api.deps import get_token_codec

    return get_token_codec().encode({"sub": str(user_id), "roleMask": role_mask}, ttl_seconds=3600)


async def _run_endpoint(client, name: str, build_request, n_requests: int, concurrency: int) -> EndpointResult:
    result = EndpointResult(name=name)
    semaphore = asyncio.Semaphore(concurrency)

    async def one(index: int) -> None:
        method, path, kwargs = build_request(index)
        started = time.perf_counter()
        try:
            response = await client.request(method, path, **kwargs)
            elapsed_ms = (time.perf_counter() - started) * 1000
            result.latencies_ms.append(elapsed_ms)
            result.statuses[response.status_code] = result.statuses.get(response.status_code, 0) + 1
        except Exception:
            result.errors += 1

    async def guarded(index: int) -> None:
        async with semaphore:
            await one(index)

    await asyncio.gather(*(guarded(i) for i in range(n_requests)))
    return result


def _build_scenarios(rng: random.Random, n_materials: int, user_token: str, admin_token: str):
    schools = [f"perf-school-{i}" for i in range(20)]
    keywords = ["复习", "真题", "笔记", "习题", "课件"]

    def materials_list(_i: int):
        params = {"page": rng.randint(1, 20), "size": 20, "sort": rng.choice(["latest", "downloads", "price"])}
        return "GET", "/api/materials", {"params": params}

    def materials_detail_anonymous(_i: int):
        return "GET", f"/api/materials/{MATERIAL_ID_BASE + rng.randint(1, n_materials)}", {}

    def materials_detail_logged_in(_i: int):
        headers = {"Authorization": f"Bearer {user_token}"}
        return "GET", f"/api/materials/{MATERIAL_ID_BASE + rng.randint(1, n_materials)}", {"headers": headers}

    def materials_search(_i: int):
        params = {"keyword": rng.choice(keywords), "page": 1, "size": 20}
        return "GET", "/api/materials", {"params": params}

    def requests_list(_i: int):
        return "GET", "/api/requests", {"params": {"limit": 20, "offset": rng.randint(0, 200)}}

    def market_list(_i: int):
        params = {"page": rng.randint(1, 10), "size": 20, "school": rng.choice(schools)}
        return "GET", "/api/market", {"params": params}

    def comments_list(_i: int):
        params = {"materialId": MATERIAL_ID_BASE + rng.randint(1, n_materials), "page": 0, "size": 20}
        return "GET", "/api/comments", {"params": params}

    def leaderboard(_i: int):
        return "GET", "/api/leaderboard/contributors", {"params": {"limit": 8}}

    def batch_submissions_admin_list(_i: int):
        headers = {"Authorization": f"Bearer {admin_token}"}
        return "GET", "/api/admin/batch-submissions", {"headers": headers, "params": {"page": 0, "size": 50}}

    return {
        "materials_list": materials_list,
        "materials_detail_anonymous": materials_detail_anonymous,
        "materials_detail_logged_in": materials_detail_logged_in,
        "materials_search": materials_search,
        "requests_list": requests_list,
        "market_list": market_list,
        "comments_list": comments_list,
        "leaderboard_contributors": leaderboard,
        "batch_submissions_admin_list": batch_submissions_admin_list,
    }


async def main_async(args: argparse.Namespace) -> None:
    import httpx

    rng = random.Random(20260926)
    user_token = _bearer_token(USER_ID_BASE + 2, 1)
    admin_token = _bearer_token(USER_ID_BASE + 1, 8)
    scenarios = _build_scenarios(rng, args.materials, user_token, admin_token)

    if args.only:
        scenarios = {name: fn for name, fn in scenarios.items() if name in args.only}

    results = []
    async with httpx.AsyncClient(base_url=args.base_url, timeout=30.0) as client:
        if not args.no_warmup:
            # Prime per-process caches (schema introspection, the public read
            # cache, etc.) sequentially before measuring. Without this, the
            # first endpoint measured absorbs a one-time cold-start cost
            # (e.g. SQLAlchemy's Inspector opening its own connection to read
            # table columns) that has nothing to do with steady-state
            # request handling and, at concurrency, can transiently exceed a
            # small dev SQLite connection pool.
            for name, build_request in scenarios.items():
                await _run_endpoint(client, name, build_request, n_requests=3, concurrency=1)

        for name, build_request in scenarios.items():
            started = time.perf_counter()
            result = await _run_endpoint(client, name, build_request, args.requests, args.concurrency)
            wall = time.perf_counter() - started
            summary = result.summary(wall)
            results.append(summary)
            print(json.dumps(summary, ensure_ascii=False))

    if args.out:
        with open(args.out, "w") as handle:
            json.dump(results, handle, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    parser.add_argument("--requests", type=int, default=300)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--materials", type=int, default=5000)
    parser.add_argument("--out", default=None)
    parser.add_argument("--only", nargs="*", default=None)
    parser.add_argument("--no-warmup", action="store_true")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
