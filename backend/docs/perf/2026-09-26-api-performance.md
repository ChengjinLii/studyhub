# API performance pass — 2026-09-26

Follow-up to the same-day security/money review (`fix/payout-settlement-integrity`).
This pass focuses on the highest-impact remaining API/performance problems on
the FastAPI backend, verified with real measurements before changing anything.

## Method

1. **Dataset**: `backend/scripts/perf_seed_data.py` bulk-inserts synthetic rows
   directly via the SQLAlchemy models (not through the service layer, which
   does OSS/validation work that makes seeding 5k+ materials impractically
   slow) into a scratch SQLite file under `/tmp` — never the repo's
   `.local-dev` database. Seeded: 200 users, 5,000 materials, 20,000
   comments, 50,000 material views, 300 market items, 300 requests, 60 batch
   submissions (3 items each, half with one published item). All synthetic
   ids are offset well clear of the app's static demo-seed fixture
   (`fixtures/runtime/read_api_seed.json`, ids 101-104/201-202/401-402/9001+)
   so each list endpoint's one-time "has the demo data been inserted yet"
   bootstrap check (`*Repository.ensure_seed_bootstrap`) settles immediately
   instead of colliding with synthetic rows and redoing work every request.

2. **Load test**: `backend/scripts/perf_load_test.py` is a small asyncio/httpx
   client that hits the hot public endpoints (materials list/detail/search,
   requests list, market list, comments, leaderboard, admin batch
   submissions list) at a fixed concurrency, with a short single-threaded
   warm-up pass first (primes per-process caches, e.g. schema introspection,
   so the first measured endpoint doesn't absorb a one-time cold-start cost),
   then reports p50/p95/p99 latency and RPS per endpoint.

3. **Query counting**: the app already ships per-request SQL query counting
   (`app/core/query_timing.py`, logged as `db_query_count`/`db_query_ms` in
   the JSON access log — see `app/main.py`'s `record_http_observability`
   middleware). Query-count evidence below comes straight from that, no new
   instrumentation needed.

4. **Server**: uvicorn against the seeded SQLite file, `STUDYHUB_ENVIRONMENT=local-dev`,
   on `127.0.0.1:18931` (killed after use). Before/after numbers come from
   `git stash` / `git stash pop` on the disposable server worktree (never on
   the local clone) around the same seeded database and process, at
   concurrency 8 / 150 requests per endpoint (chosen because SQLite's
   *default* sync engine pool is small — see "Deliberately not changed"; this
   keeps the comparison clean and about the code, not about SQLite's dev-only
   pool sizing).

### A real constraint that shaped what could be measured live

`get_detail_async`'s fan-out and `_compat_file_key_sql`'s schema check only
run when `settings.requires_private_env_file` is true (preview/production).
That mode's own runtime validation (`app/core/config_validation.py`)
**forbids SQLite outright** and requires a real private env file — by
design, so nobody points a "preview" process at a scratch SQLite file by
accident. It cannot be satisfied locally without a real MySQL instance,
which is out of scope here. So those two fixes are verified two ways
instead of one end-to-end HTTP benchmark:
- Unit tests that assert the *shape* of the fix directly (session count,
  introspection call count) — see `backend/tests/test_materials_compat_read.py`.
- `backend/scripts/perf_compat_detail_bench.py`, which builds a
  `MaterialsService` directly (like the compat tests do) and points it at a
  small, explicitly pool-limited async SQLite engine sized like the real
  production pool (`pool_size=10, max_overflow=20` — see
  `app/core/config.py`), with the individual loader methods stubbed to run
  one real trivial query (`SELECT 1`, so it works on any schema and still
  forces a real pool checkout) plus a configurable simulated per-query
  latency standing in for a real MySQL round trip. This isolates exactly
  what changed — connections needed per request — from dataset content.

## Fixes (5 commits)

### 1. `perf: share one async session for material detail auxiliary reads`

**Problem**: `MaterialsService.get_detail_async` (the async/compat detail
path, live in preview/production) opened one new async session — one
connection checked out from the async pool (`pool_size=10` +
`max_overflow=20` = 30 in production) — for the main row query, and again
for each of up to 8 auxiliary reads (tags, comment count, versions, reviews,
favorited, liked, my rating, paid access), all fired concurrently via
`asyncio.gather`. A single logged-in detail request could need **up to ~10
connections at once**.

**Fix**: all these reads now share one `async_session_scope()` and run
sequentially on it. Peak connections per request: 1 (verified in
`test_async_legacy_material_detail_uses_one_shared_session`).

**Measured** (`perf_compat_detail_bench.py`, pool = 10+20 = 30, simulated
5ms/query):

| concurrent logged-in detail requests | old peak connections | new peak connections | pool capacity |
|---:|---:|---:|---:|
| 5  | 25 | 5  | 30 |
| 10 | 30 (100%, saturated) | 10 (33%) | 30 |
| 25 | 30 (100%, zero headroom for any other traffic) | 25 (83%) | 30 |

At just 3-4 concurrent logged-in detail views, the old code alone could
consume the *entire* production connection budget, starving every other
endpoint sharing that pool. The new code needs ~30 concurrent logged-in
detail requests to reach the same point.

**Trade-off, measured honestly**: the auxiliary reads used to run in
parallel (fast when the pool has room) and now run sequentially on one
connection. At 15 concurrent requests / 20ms simulated query latency, wall
time for the batch went from 138ms (old, parallel, contending for the pool)
to 236ms (new, sequential, but never contends past 1 connection/request).
This is the intended trade: a bounded, small amount of per-request latency
for the auxiliary section in exchange for not being able to exhaust the
shared connection pool.

### 2. `perf: cache materials-table column introspection per engine`

**Problem**: `_compat_file_key_sql` (used by every compat list/detail/
preview/download read) called `inspect(bind).get_columns("materials")` on
every single call to check whether the post-migration `file_storage_key`
column exists yet. `Inspector` reflection **opens its own separate
connection** (`sqlalchemy/engine/reflection.py:_init_engine` does
`engine.connect().close()`), on top of whatever connection the request's own
session was already using — an extra, uncached connection checkout, and on
the async path, a blocking call made from inside a coroutine.

**Fix**: cache the column set per engine (a schema that doesn't change while
the process runs), keyed by a *weak reference to the engine object itself*
rather than its URL — tests spin up many distinct SQLite `:memory:` engines
that share the identical URL string but intentionally model different
(legacy vs. current) schemas, so a URL-keyed cache would leak results
between them; a real fallback (previous behavior) is kept for any bind that
can't be introspected.

**Measured** (`test_compat_file_key_sql_caches_schema_introspection_per_engine`):
3 calls against one engine → schema introspection actually ran **once**
(was 3/3); a second, independent engine gets its own cache entry (introspection
count 2, not reusing the first engine's answer) — proving no cross-database leakage.

### 3. `fix: release batch item locks before the object storage copy`

**Problem**: `GET /api/admin/batch-submissions/{id}/items/{id}/file` calls
`download_item`, which takes `SELECT ... FOR UPDATE` locks on the batch and
item rows (to guard against a concurrent status change while checking
access) — read-only, no mutation follows. The route then held that same
request session (and its locks) open for the entire object-storage copy
before returning a response, since `get_db_session()`'s dependency never
commits until the request tears down.

**Fix**: commit immediately after the read-only lock check, before the
(potentially slow, network-bound) copy. Verified with
`test_private_download_releases_locks_before_object_copy` (asserts
`Session.commit()` happens before `asset_store.copy_to_path()`, not after).

**Not independently load-tested**: this is a lock-contention fix, not a
latency-under-load fix — its benefit only shows up when something else
needs the same batch/item row *during* a slow OSS transfer, which isn't
something a single-process local benchmark reproduces meaningfully (and
SQLite doesn't implement row-level `FOR UPDATE` semantics the way MySQL
does, so a local timing test would prove nothing about production). The
qualitative before/after is: locks held for the full transfer duration →
locks held only for the access check.

### 4. `perf: batch-load items and publications in batch submissions list`

**Problem**: `list_batches` called `_serialize` per batch, and `_serialize`
always ran its own items query and its own publications query for that one
batch — a page of N batches did `1 (count) + 1 (batches) + 2N` queries.

**Fix**: load the whole page's items and publications in two queries up
front, pass them into `_serialize` (which still falls back to its own
per-batch queries for the single-batch callers: create/detail/submit/
review/publish).

**Measured** (`GET /api/admin/batch-submissions`, page size 50, seeded 60
batches / ~180 items / ~30 publications; concurrency 8, 150 requests):

| metric | before | after |
|---|---:|---:|
| queries/request | 43 (constant — same page every time) | 5 |
| p50 | 502 ms | 226 ms |
| p95 | 754 ms | 308 ms |
| p99 | 813 ms | 336 ms |
| throughput | 15.8 req/s | 35.2 req/s |

Also verified with `test_list_batches_query_count_is_independent_of_page_size`:
requesting 2 rows vs. 6 rows from the same data now costs the *same* number
of queries (was proportional to rows returned).

### 5. `fix: invalidate anonymous read cache on report auto-hide/restore`

**Problem**: submitting a report that crosses the auto-hide threshold (3
reports), or an admin restoring a previously-hidden target, flips a
material/comment/market item's visibility — but neither `/api/reports` nor
`/api/admin/reports/{id}` invalidated the anonymous public-read cache
(`app/core/public_read_cache.py`, 30s TTL by default). A popular item that
was already cached would keep showing as visible (or, after a restore, keep
404ing) for up to the cache TTL, not immediately. Also fixed
`/api/comments/{id}/report` (a separate entry point into the same auto-hide
path) to invalidate `materials:detail` too, matching create/update/delete,
since hiding a comment changes the `commentCount` embedded in the cached
material detail payload.

**Measured**: staleness window before a hide/restore is reflected to
anonymous readers: up to 30s (cache TTL) → 0s (immediate). Verified with
`test_report_auto_hide_invalidates_anonymous_market_cache` and
`test_report_restore_invalidates_anonymous_market_cache` (warm the
anonymous cache, cross the auto-hide threshold / restore, assert the very
next anonymous read already reflects the change).

## Other endpoints (no code change, confirmed no regression)

At concurrency 8 / 150 requests, `materials_detail_anonymous`,
`materials_detail_logged_in`, `requests_list`, `market_list`,
`comments_list`, and `leaderboard_contributors` were all statistically
unchanged before/after (same code path, same query counts per the access
log), all 0 errors, p50s in the 16-100ms range.

## Deliberately not changed

- **`list_materials` / `list_materials_async`'s non-compat (ORM) path**
  (`app/services/materials_service.py`) loads every visible material into
  Python, filters, sorts, and paginates in memory on every call. This is
  real and slow (p50 ~6-10s against 5,000 rows in this benchmark) — but it
  only runs when `requires_private_env_file` is false, i.e. **local-dev and
  tests only**. Production always takes `_compat_list_materials`, which
  already does proper SQL-level `LIMIT`/`OFFSET` and a separate `COUNT(*)`
  (verified: `/api/materials` averaged 1.0 query/request in this benchmark's
  local-dev run). Rewriting a local-dev-only fallback for zero production
  benefit isn't worth the risk on a live site; flagging it here in case
  someone later flips that flag for local dev and hits the same wall.
- **`MaterialRepository._table_columns`/`_has_table_column`** already had a
  cache (unlike `_compat_file_key_sql`) — a genuine first-call-per-process
  cold start (it also opens its own connection via `Inspector`), not a
  per-request cost. Left alone: it self-resolves after the first successful
  call, and production's pool (30) has more headroom than this benchmark's
  default SQLite dev pool (5+10=15, not configurable for SQLite — see
  `app/core/db.py`/`app/core/async_db.py`, which intentionally skip
  `pool_size`/`max_overflow` for SQLite) for a handful of one-time
  introspection queries at boot.
- **New DB indexes**: none added. `EXPLAIN`-worthy candidates (e.g.
  `material_views(material_id, viewer_token_hash)`, `comments(material_id,
  status)`) weren't found to be missing an index that mattered at this
  dataset size once the query-count problems above were fixed; the
  remaining latency is dominated by query *count*, not per-query plan cost.
  Not adding speculative indexes on a live MySQL table without evidence.
- **Frontend**: not touched. `next build` output sizes and page bundle sizes
  are unchanged from main; no repeated-client-fetch issues found on the
  pages exercised by this pass.

## Gates (server worktree, after final sync)

- Backend: `pytest backend/tests` — 509 passed, 1 skipped (0 failed).
- `ruff check backend/app backend/tests` — all checks passed.
- Frontend: `npm run check` (typecheck + lint) — passed; `npm run test:unit`
  — 282 passed; `npm run build` — succeeded.
- `node scripts/check-code-size.mjs` — passed (11 file budgets, including
  `batch_submission_service.py` at 586/600 lines after this change).

## Risks for production rollout

- No schema migration needed — all 5 fixes are application-code-only.
- The `get_detail_async` change trades some per-request latency in the
  auxiliary-reads section for far lower peak connection usage; worth
  watching materials-detail p95/p99 for logged-in users after deploy, though
  the measured trade (order of ~100ms at simulated MySQL-like per-query
  latency) is small next to the alternative (pool-timeout 500s under load).
- The batch-submissions list change assumes `Item`/`Publication` result sets
  for one admin page (≤50 batches) fit comfortably in memory grouped by
  batch id — true today (batches cap at a handful of items each) but would
  need revisiting if batch sizes grow substantially.
- The report cache invalidation fix calls `invalidate_prefixes` on every
  report submission/restore, not only when auto-hide/restore actually fires.
  Report volume is low, so this is cheap; noted here in case that changes.
