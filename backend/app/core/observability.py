from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from threading import Lock
import time

from app.core.config import Settings


def _sanitize_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


@dataclass(slots=True)
class _Aggregate:
    count: int = 0
    total_seconds: float = 0.0
    max_seconds: float = 0.0

    def observe(self, duration_seconds: float) -> None:
        bounded = max(0.0, float(duration_seconds))
        self.count += 1
        self.total_seconds += bounded
        self.max_seconds = max(self.max_seconds, bounded)


class RuntimeMetrics:
    """轻量运行时指标收集器。

    不依赖额外中间件或外部服务，先提供最基本的 HTTP / worker 指标，
    让 preview / production 至少具备统一的 `/metrics` 暴露面。
    """

    def __init__(self) -> None:
        self.started_at = time.time()
        self._lock = Lock()
        self._http_requests_total: dict[tuple[str, str, str], int] = defaultdict(int)
        self._http_request_durations: dict[tuple[str, str], _Aggregate] = defaultdict(_Aggregate)
        self._worker_jobs_total: dict[tuple[str, str], int] = defaultdict(int)
        self._worker_job_durations: dict[tuple[str, str], _Aggregate] = defaultdict(_Aggregate)
        self._mcp_tool_calls_total: dict[tuple[str, str], int] = defaultdict(int)
        self._mcp_tool_durations: dict[tuple[str, str], _Aggregate] = defaultdict(_Aggregate)

    def clear(self) -> None:
        with self._lock:
            self._http_requests_total.clear()
            self._http_request_durations.clear()
            self._worker_jobs_total.clear()
            self._worker_job_durations.clear()
            self._mcp_tool_calls_total.clear()
            self._mcp_tool_durations.clear()
            self.started_at = time.time()

    def record_http_request(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        method_key = (method or "UNKNOWN").upper()
        route_key = route or "/"
        status_key = str(int(status_code or 500))
        with self._lock:
            self._http_requests_total[(method_key, route_key, status_key)] += 1
            self._http_request_durations[(method_key, route_key)].observe(duration_seconds)

    def record_worker_job(
        self,
        *,
        job: str,
        status: str,
        duration_seconds: float,
    ) -> None:
        job_key = job or "unknown"
        status_key = (status or "unknown").lower()
        with self._lock:
            self._worker_jobs_total[(job_key, status_key)] += 1
            self._worker_job_durations[(job_key, status_key)].observe(duration_seconds)

    def record_mcp_tool_call(
        self,
        *,
        tool: str,
        status: str,
        duration_seconds: float,
    ) -> None:
        tool_key = tool or "unknown"
        status_key = (status or "unknown").lower()
        with self._lock:
            self._mcp_tool_calls_total[(tool_key, status_key)] += 1
            self._mcp_tool_durations[(tool_key, status_key)].observe(duration_seconds)

    def render_prometheus(self, settings: Settings) -> str:
        lines: list[str] = [
            "# HELP studyhub_app_info Static app metadata.",
            "# TYPE studyhub_app_info gauge",
            (
                'studyhub_app_info{service="%s",environment="%s",git_sha="%s"} 1'
                % (
                    _sanitize_label(settings.app_name),
                    _sanitize_label(settings.environment),
                    _sanitize_label(settings.resolved_build_git_sha),
                )
            ),
            "# HELP studyhub_process_start_time_seconds Process start timestamp.",
            "# TYPE studyhub_process_start_time_seconds gauge",
            f"studyhub_process_start_time_seconds {self.started_at:.6f}",
            "# HELP studyhub_http_requests_total HTTP requests handled by the API.",
            "# TYPE studyhub_http_requests_total counter",
        ]
        with self._lock:
            for (method, route, status_code), count in sorted(self._http_requests_total.items()):
                lines.append(
                    'studyhub_http_requests_total{method="%s",route="%s",status_code="%s"} %d'
                    % (_sanitize_label(method), _sanitize_label(route), _sanitize_label(status_code), count)
                )
            lines.extend(
                [
                    "# HELP studyhub_http_request_duration_seconds_count HTTP request count by route.",
                    "# TYPE studyhub_http_request_duration_seconds_count counter",
                    "# HELP studyhub_http_request_duration_seconds_sum HTTP request duration sum by route.",
                    "# TYPE studyhub_http_request_duration_seconds_sum counter",
                    "# HELP studyhub_http_request_duration_seconds_max HTTP request max duration by route.",
                    "# TYPE studyhub_http_request_duration_seconds_max gauge",
                ]
            )
            for (method, route), aggregate in sorted(self._http_request_durations.items()):
                labels = 'method="%s",route="%s"' % (_sanitize_label(method), _sanitize_label(route))
                lines.append(f"studyhub_http_request_duration_seconds_count{{{labels}}} {aggregate.count}")
                lines.append(f"studyhub_http_request_duration_seconds_sum{{{labels}}} {aggregate.total_seconds:.6f}")
                lines.append(f"studyhub_http_request_duration_seconds_max{{{labels}}} {aggregate.max_seconds:.6f}")
            lines.extend(
                [
                    "# HELP studyhub_worker_jobs_total Worker jobs executed by name and status.",
                    "# TYPE studyhub_worker_jobs_total counter",
                    "# HELP studyhub_worker_job_duration_seconds_count Worker job count by name and status.",
                    "# TYPE studyhub_worker_job_duration_seconds_count counter",
                    "# HELP studyhub_worker_job_duration_seconds_sum Worker job duration sum by name and status.",
                    "# TYPE studyhub_worker_job_duration_seconds_sum counter",
                ]
            )
            for (job, status), count in sorted(self._worker_jobs_total.items()):
                labels = 'job="%s",status="%s"' % (_sanitize_label(job), _sanitize_label(status))
                lines.append(f"studyhub_worker_jobs_total{{{labels}}} {count}")
                aggregate = self._worker_job_durations[(job, status)]
                lines.append(f"studyhub_worker_job_duration_seconds_count{{{labels}}} {aggregate.count}")
                lines.append(f"studyhub_worker_job_duration_seconds_sum{{{labels}}} {aggregate.total_seconds:.6f}")
            lines.extend(
                [
                    "# HELP studyhub_mcp_tool_calls_total MCP tool calls by tool and status.",
                    "# TYPE studyhub_mcp_tool_calls_total counter",
                    "# HELP studyhub_mcp_tool_duration_seconds_count MCP tool call count by tool and status.",
                    "# TYPE studyhub_mcp_tool_duration_seconds_count counter",
                    "# HELP studyhub_mcp_tool_duration_seconds_sum MCP tool call duration sum by tool and status.",
                    "# TYPE studyhub_mcp_tool_duration_seconds_sum counter",
                ]
            )
            for (tool, status), count in sorted(self._mcp_tool_calls_total.items()):
                labels = 'tool="%s",status="%s"' % (_sanitize_label(tool), _sanitize_label(status))
                lines.append(f"studyhub_mcp_tool_calls_total{{{labels}}} {count}")
                aggregate = self._mcp_tool_durations[(tool, status)]
                lines.append(f"studyhub_mcp_tool_duration_seconds_count{{{labels}}} {aggregate.count}")
                lines.append(f"studyhub_mcp_tool_duration_seconds_sum{{{labels}}} {aggregate.total_seconds:.6f}")
        lines.append("")
        return "\n".join(lines)


_RUNTIME_METRICS = RuntimeMetrics()


def get_runtime_metrics() -> RuntimeMetrics:
    return _RUNTIME_METRICS
