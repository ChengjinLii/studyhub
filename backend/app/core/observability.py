from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import hashlib
from threading import Lock
import time

from app.core.config import Settings


DURATION_BUCKETS_SECONDS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


def _sanitize_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _format_bucket(value: float) -> str:
    return ("%g" % value)


@dataclass(slots=True)
class _Aggregate:
    count: int = 0
    total_seconds: float = 0.0
    max_seconds: float = 0.0
    bucket_counts: dict[float, int] = field(default_factory=lambda: {bucket: 0 for bucket in DURATION_BUCKETS_SECONDS})

    def observe(self, duration_seconds: float) -> None:
        bounded = max(0.0, float(duration_seconds))
        self.count += 1
        self.total_seconds += bounded
        self.max_seconds = max(self.max_seconds, bounded)
        for bucket in DURATION_BUCKETS_SECONDS:
            if bounded <= bucket:
                self.bucket_counts[bucket] += 1


def _append_duration_buckets(lines: list[str], *, metric_name: str, labels: str, aggregate: _Aggregate) -> None:
    for bucket in DURATION_BUCKETS_SECONDS:
        bucket_labels = f'{labels},le="{_format_bucket(bucket)}"'
        lines.append(f"{metric_name}_bucket{{{bucket_labels}}} {aggregate.bucket_counts[bucket]}")
    lines.append(f'{metric_name}_bucket{{{labels},le="+Inf"}} {aggregate.count}')


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
        self._cache_events_total: dict[tuple[str, str, str], int] = defaultdict(int)
        self._security_events_total: dict[tuple[str, str], int] = defaultdict(int)
        self._errors_total: dict[tuple[str, str, str, str], int] = defaultdict(int)
        self._ai_agent_runs_total: dict[tuple[str, str, str, str, str], int] = defaultdict(int)
        self._ai_agent_run_durations: dict[tuple[str, str, str, str, str], _Aggregate] = defaultdict(_Aggregate)
        self._ai_agent_feedback_total: dict[tuple[str, str, str, str], int] = defaultdict(int)

    def clear(self) -> None:
        with self._lock:
            self._http_requests_total.clear()
            self._http_request_durations.clear()
            self._worker_jobs_total.clear()
            self._worker_job_durations.clear()
            self._mcp_tool_calls_total.clear()
            self._mcp_tool_durations.clear()
            self._cache_events_total.clear()
            self._security_events_total.clear()
            self._errors_total.clear()
            self._ai_agent_runs_total.clear()
            self._ai_agent_run_durations.clear()
            self._ai_agent_feedback_total.clear()
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

    def record_cache_event(self, *, namespace: str, backend: str, event: str) -> None:
        namespace_key = namespace or "unknown"
        backend_key = backend or "unknown"
        event_key = (event or "unknown").lower()
        with self._lock:
            self._cache_events_total[(namespace_key, backend_key, event_key)] += 1

    def record_security_event(self, *, event: str, reason: str) -> None:
        event_key = (event or "unknown").lower()
        reason_key = reason or "unknown"
        with self._lock:
            self._security_events_total[(event_key, reason_key)] += 1

    def record_error(self, *, exception_type: str, route: str, status_code: int) -> str:
        kind = _bounded_label(exception_type or "unknown")
        route_key = (route or "/")[:160]
        status_key = str(int(status_code or 500))
        canonical = f"{kind}|{route_key}|{status_key}"
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
        with self._lock:
            self._errors_total[(fingerprint, kind, route_key, status_key)] += 1
        return fingerprint

    def record_ai_agent_run(
        self,
        *,
        provider: str,
        status: str,
        pdf_evidence: bool,
        memory_context: bool,
        course_memory_card: bool,
        duration_seconds: float,
    ) -> None:
        labels = (
            _bounded_label(provider or "local"),
            _bounded_label((status or "unknown").lower()),
            "yes" if pdf_evidence else "no",
            "yes" if memory_context else "no",
            "yes" if course_memory_card else "no",
        )
        with self._lock:
            self._ai_agent_runs_total[labels] += 1
            self._ai_agent_run_durations[labels].observe(duration_seconds)

    def record_ai_agent_feedback(
        self,
        *,
        hook: str,
        status: str,
        personal_memory: bool,
        selected_materials: bool,
    ) -> None:
        labels = (
            _bounded_label(hook or "unknown"),
            _bounded_label((status or "unknown").lower()),
            "yes" if personal_memory else "no",
            "yes" if selected_materials else "no",
        )
        with self._lock:
            self._ai_agent_feedback_total[labels] += 1

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
                    "# HELP studyhub_http_request_duration_seconds HTTP request duration histogram by route.",
                    "# TYPE studyhub_http_request_duration_seconds histogram",
                    "# HELP studyhub_http_request_duration_seconds_max HTTP request max duration by route.",
                    "# TYPE studyhub_http_request_duration_seconds_max gauge",
                ]
            )
            for (method, route), aggregate in sorted(self._http_request_durations.items()):
                labels = 'method="%s",route="%s"' % (_sanitize_label(method), _sanitize_label(route))
                _append_duration_buckets(
                    lines,
                    metric_name="studyhub_http_request_duration_seconds",
                    labels=labels,
                    aggregate=aggregate,
                )
                lines.append(f"studyhub_http_request_duration_seconds_count{{{labels}}} {aggregate.count}")
                lines.append(f"studyhub_http_request_duration_seconds_sum{{{labels}}} {aggregate.total_seconds:.6f}")
                lines.append(f"studyhub_http_request_duration_seconds_max{{{labels}}} {aggregate.max_seconds:.6f}")
            lines.extend(
                [
                    "# HELP studyhub_worker_jobs_total Worker jobs executed by name and status.",
                    "# TYPE studyhub_worker_jobs_total counter",
                    "# HELP studyhub_worker_job_duration_seconds Worker job duration histogram by name and status.",
                    "# TYPE studyhub_worker_job_duration_seconds histogram",
                ]
            )
            for (job, status), count in sorted(self._worker_jobs_total.items()):
                labels = 'job="%s",status="%s"' % (_sanitize_label(job), _sanitize_label(status))
                lines.append(f"studyhub_worker_jobs_total{{{labels}}} {count}")
                aggregate = self._worker_job_durations[(job, status)]
                _append_duration_buckets(
                    lines,
                    metric_name="studyhub_worker_job_duration_seconds",
                    labels=labels,
                    aggregate=aggregate,
                )
                lines.append(f"studyhub_worker_job_duration_seconds_count{{{labels}}} {aggregate.count}")
                lines.append(f"studyhub_worker_job_duration_seconds_sum{{{labels}}} {aggregate.total_seconds:.6f}")
            lines.extend(
                [
                    "# HELP studyhub_mcp_tool_calls_total MCP tool calls by tool and status.",
                    "# TYPE studyhub_mcp_tool_calls_total counter",
                    "# HELP studyhub_mcp_tool_duration_seconds MCP tool call duration histogram by tool and status.",
                    "# TYPE studyhub_mcp_tool_duration_seconds histogram",
                ]
            )
            for (tool, status), count in sorted(self._mcp_tool_calls_total.items()):
                labels = 'tool="%s",status="%s"' % (_sanitize_label(tool), _sanitize_label(status))
                lines.append(f"studyhub_mcp_tool_calls_total{{{labels}}} {count}")
                aggregate = self._mcp_tool_durations[(tool, status)]
                _append_duration_buckets(
                    lines,
                    metric_name="studyhub_mcp_tool_duration_seconds",
                    labels=labels,
                    aggregate=aggregate,
                )
                lines.append(f"studyhub_mcp_tool_duration_seconds_count{{{labels}}} {aggregate.count}")
                lines.append(f"studyhub_mcp_tool_duration_seconds_sum{{{labels}}} {aggregate.total_seconds:.6f}")
            lines.extend(
                [
                    "# HELP studyhub_cache_events_total Cache events by namespace, backend, and event.",
                    "# TYPE studyhub_cache_events_total counter",
                ]
            )
            for (namespace, backend, event), count in sorted(self._cache_events_total.items()):
                labels = 'namespace="%s",backend="%s",event="%s"' % (
                    _sanitize_label(namespace),
                    _sanitize_label(backend),
                    _sanitize_label(event),
                )
                lines.append(f"studyhub_cache_events_total{{{labels}}} {count}")
            lines.extend(
                [
                    "# HELP studyhub_security_events_total Security events by type and reason.",
                    "# TYPE studyhub_security_events_total counter",
                ]
            )
            for (event, reason), count in sorted(self._security_events_total.items()):
                labels = 'event="%s",reason="%s"' % (_sanitize_label(event), _sanitize_label(reason))
                lines.append(f"studyhub_security_events_total{{{labels}}} {count}")
            lines.extend(
                [
                    "# HELP studyhub_errors_total Handled server errors grouped by a stable privacy-safe fingerprint.",
                    "# TYPE studyhub_errors_total counter",
                ]
            )
            for (fingerprint, kind, route, status_code), count in sorted(self._errors_total.items()):
                labels = 'fingerprint="%s",kind="%s",route="%s",status_code="%s"' % (
                    _sanitize_label(fingerprint),
                    _sanitize_label(kind),
                    _sanitize_label(route),
                    _sanitize_label(status_code),
                )
                lines.append(f"studyhub_errors_total{{{labels}}} {count}")
            lines.extend(
                [
                    "# HELP studyhub_ai_agent_runs_total StudyHub Agent recommendation runs by provider, status, and bounded context usage.",
                    "# TYPE studyhub_ai_agent_runs_total counter",
                    "# HELP studyhub_ai_agent_run_duration_seconds StudyHub Agent run duration histogram by provider, status, and bounded context usage.",
                    "# TYPE studyhub_ai_agent_run_duration_seconds histogram",
                    "# HELP studyhub_ai_agent_run_duration_seconds_max StudyHub Agent run max duration by provider, status, and bounded context usage.",
                    "# TYPE studyhub_ai_agent_run_duration_seconds_max gauge",
                ]
            )
            for (provider, status, pdf_evidence, memory_context, course_memory_card), count in sorted(
                self._ai_agent_runs_total.items()
            ):
                labels = 'provider="%s",status="%s",pdf_evidence="%s",memory_context="%s",course_memory_card="%s"' % (
                    _sanitize_label(provider),
                    _sanitize_label(status),
                    _sanitize_label(pdf_evidence),
                    _sanitize_label(memory_context),
                    _sanitize_label(course_memory_card),
                )
                lines.append(f"studyhub_ai_agent_runs_total{{{labels}}} {count}")
                aggregate = self._ai_agent_run_durations[(provider, status, pdf_evidence, memory_context, course_memory_card)]
                _append_duration_buckets(
                    lines,
                    metric_name="studyhub_ai_agent_run_duration_seconds",
                    labels=labels,
                    aggregate=aggregate,
                )
                lines.append(f"studyhub_ai_agent_run_duration_seconds_count{{{labels}}} {aggregate.count}")
                lines.append(f"studyhub_ai_agent_run_duration_seconds_sum{{{labels}}} {aggregate.total_seconds:.6f}")
                lines.append(f"studyhub_ai_agent_run_duration_seconds_max{{{labels}}} {aggregate.max_seconds:.6f}")
            lines.extend(
                [
                    "# HELP studyhub_ai_agent_feedback_total StudyHub Agent explicit feedback events by hook, status, and bounded memory context.",
                    "# TYPE studyhub_ai_agent_feedback_total counter",
                ]
            )
            for (hook, status, personal_memory, selected_materials), count in sorted(self._ai_agent_feedback_total.items()):
                labels = 'hook="%s",status="%s",personal_memory="%s",selected_materials="%s"' % (
                    _sanitize_label(hook),
                    _sanitize_label(status),
                    _sanitize_label(personal_memory),
                    _sanitize_label(selected_materials),
                )
                lines.append(f"studyhub_ai_agent_feedback_total{{{labels}}} {count}")
        lines.append("")
        return "\n".join(lines)


_RUNTIME_METRICS = RuntimeMetrics()


def get_runtime_metrics() -> RuntimeMetrics:
    return _RUNTIME_METRICS


def _bounded_label(value: str) -> str:
    normalized = (value or "unknown").strip().lower().replace(" ", "_")
    return normalized[:64] or "unknown"
