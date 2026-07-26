from __future__ import annotations

import argparse
import logging
import time
from time import perf_counter

from app.api.deps import clear_dependency_caches, get_worker_service
from app.core.config import get_settings
from app.core.db import prepare_database_runtime, session_scope
from app.core.logging import configure_logging
from app.core.observability import get_runtime_metrics


logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="StudyHub FastAPI worker runner")
    parser.add_argument(
        "--job",
        default="all",
        choices=[
            "all",
            "settlement",
            "request-maintenance",
            "request-timeout",
            "timeout",
            "request-refund",
            "refund",
            "payout-transfer",
            "transfer",
            "agentic",
        ],
    )
    parser.add_argument("--once", action="store_true", help="仅执行一轮任务后退出")
    parser.add_argument("--interval-seconds", type=int, default=300, help="非 once 模式下的轮询间隔")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(
        settings.log_level,
        log_format=settings.log_format,
        access_log_enabled=settings.access_log_enabled,
        service_name="studyhub-worker",
        environment=settings.environment,
        build_git_sha=settings.resolved_build_git_sha,
    )
    prepare_database_runtime()
    clear_dependency_caches()
    worker_service = get_worker_service()
    logger.info("Worker booted in %s mode", settings.environment)

    def run_once() -> None:
        started_at = perf_counter()
        job_status = "success"
        job_result: dict[str, object] | None = None
        with session_scope() as session:
            try:
                job_result = worker_service.run_named_job(session, args.job)
            except Exception:
                job_status = "failed"
                raise
            finally:
                duration_seconds = perf_counter() - started_at
                get_runtime_metrics().record_worker_job(
                    job=args.job,
                    status=job_status,
                    duration_seconds=duration_seconds,
                )
                logger.info(
                    "Worker job finished",
                    extra={
                        "event": "worker_job",
                        "environment": settings.environment,
                        "job": args.job,
                        "job_status": job_status,
                        "job_result": job_result,
                        "duration_ms": round(duration_seconds * 1000, 2),
                    },
                )

    run_once()
    if args.once:
        return 0

    interval_seconds = max(30, int(args.interval_seconds))
    while True:
        time.sleep(interval_seconds)
        run_once()


if __name__ == "__main__":
    raise SystemExit(main())
