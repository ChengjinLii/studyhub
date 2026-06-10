from __future__ import annotations

from contextvars import ContextVar, Token
from datetime import UTC, datetime
import json
import logging
from logging.config import dictConfig
import re
from typing import Any


_REQUEST_ID_CTX: ContextVar[str] = ContextVar("studyhub_request_id", default="-")
_REQUEST_METHOD_CTX: ContextVar[str] = ContextVar("studyhub_request_method", default="-")
_REQUEST_PATH_CTX: ContextVar[str] = ContextVar("studyhub_request_path", default="-")
_SERVICE_NAME = "studyhub-backend"
_SERVICE_ENVIRONMENT = "local-dev"
_SERVICE_VERSION = "local-dev"

_SAFE_REQUEST_ID_RE = re.compile(r"[^A-Za-z0-9_.:-]")
_MAX_REQUEST_ID_LENGTH = 96
_SEVERITY_NUMBERS = {
    "DEBUG": 5,
    "INFO": 9,
    "WARNING": 13,
    "ERROR": 17,
    "CRITICAL": 21,
}
_SENSITIVE_FIELD_NAMES = {
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "private_key",
}
_STANDARD_LOG_RECORD_FIELDS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "request_id",
    "request_method",
    "request_path",
}


def sanitize_request_id(value: str | None) -> str:
    candidate = (value or "").strip()
    if not candidate:
        return "-"
    return _SAFE_REQUEST_ID_RE.sub("_", candidate)[:_MAX_REQUEST_ID_LENGTH] or "-"


def bind_request_id(request_id: str) -> Token[str]:
    return _REQUEST_ID_CTX.set(sanitize_request_id(request_id))


def reset_request_id(token: Token[str]) -> None:
    _REQUEST_ID_CTX.reset(token)


def bind_request_context(*, request_id: str, method: str, path: str) -> tuple[Token[str], Token[str], Token[str]]:
    return (
        bind_request_id(request_id),
        _REQUEST_METHOD_CTX.set(method or "-"),
        _REQUEST_PATH_CTX.set(path or "-"),
    )


def reset_request_context(tokens: tuple[Token[str], Token[str], Token[str]]) -> None:
    request_id_token, method_token, path_token = tokens
    reset_request_id(request_id_token)
    _REQUEST_METHOD_CTX.reset(method_token)
    _REQUEST_PATH_CTX.reset(path_token)


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _REQUEST_ID_CTX.get("-")
        record.request_method = _REQUEST_METHOD_CTX.get("-")
        record.request_path = _REQUEST_PATH_CTX.get("-")
        return True


def _is_sensitive_field(field_name: str) -> bool:
    normalized = field_name.lower().replace("-", "_")
    return normalized in _SENSITIVE_FIELD_NAMES or any(part in normalized for part in ("password", "secret", "token", "api_key"))


def _safe_json_value(value: Any) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_json_value(item) for item in value[:20]]
    if isinstance(value, dict):
        return {
            str(key): ("[REDACTED]" if _is_sensitive_field(str(key)) else _safe_json_value(item))
            for key, item in list(value.items())[:50]
        }
    return str(value)


class JsonFormatter(logging.Formatter):
    EXTRA_FIELDS = (
        "event",
        "environment",
        "method",
        "path",
        "status_code",
        "duration_ms",
        "client_ip",
        "job",
        "job_status",
        "job_result",
    )

    def format(self, record: logging.LogRecord) -> str:
        severity_text = record.levelname
        request_id = getattr(record, "request_id", _REQUEST_ID_CTX.get("-"))
        request_method = getattr(record, "request_method", _REQUEST_METHOD_CTX.get("-"))
        request_path = getattr(record, "request_path", _REQUEST_PATH_CTX.get("-"))
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": severity_text,
            "severityText": severity_text,
            "severityNumber": _SEVERITY_NUMBERS.get(severity_text, record.levelno),
            "logger": record.name,
            "message": record.getMessage(),
            "body": record.getMessage(),
            "requestId": request_id,
            "request.id": request_id,
            "service.name": _SERVICE_NAME,
            "service.version": _SERVICE_VERSION,
            "deployment.environment": _SERVICE_ENVIRONMENT,
        }
        if request_method != "-":
            payload["http.request.method"] = request_method
        if request_path != "-":
            payload["url.path"] = request_path
        for field_name in self.EXTRA_FIELDS:
            value = getattr(record, field_name, None)
            if value is not None:
                if field_name == "method":
                    payload["http.request.method"] = value
                elif field_name == "path":
                    payload["url.path"] = value
                elif field_name == "status_code":
                    payload["http.response.status_code"] = value
                elif field_name == "duration_ms":
                    payload["duration.ms"] = value
                elif field_name == "client_ip":
                    payload["client.address"] = value
                payload[field_name] = "[REDACTED]" if _is_sensitive_field(field_name) else _safe_json_value(value)
        attributes: dict[str, object] = {}
        known_extra_fields = set(self.EXTRA_FIELDS)
        for field_name, value in record.__dict__.items():
            if field_name in _STANDARD_LOG_RECORD_FIELDS or field_name in known_extra_fields:
                continue
            attributes[field_name] = "[REDACTED]" if _is_sensitive_field(field_name) else _safe_json_value(value)
        if attributes:
            payload["attributes"] = attributes
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(
    level: str,
    *,
    log_format: str = "text",
    access_log_enabled: bool = True,
    service_name: str = "studyhub-backend",
    environment: str = "local-dev",
    build_git_sha: str = "local-dev",
) -> None:
    global _SERVICE_NAME, _SERVICE_ENVIRONMENT, _SERVICE_VERSION
    _SERVICE_NAME = service_name
    _SERVICE_ENVIRONMENT = environment
    _SERVICE_VERSION = build_git_sha
    normalized = level.upper()
    formatter_name = "json" if log_format.lower() == "json" else "text"
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "request_context": {
                    "()": RequestContextFilter,
                }
            },
            "formatters": {
                "text": {
                    "format": "%(asctime)s %(levelname)s [%(name)s] [request_id=%(request_id)s] %(message)s",
                },
                "json": {
                    "()": JsonFormatter,
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": formatter_name,
                    "filters": ["request_context"],
                    "level": normalized,
                }
            },
            "root": {
                "handlers": ["console"],
                "level": normalized,
            },
        }
    )
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.disabled = not access_log_enabled
    uvicorn_access.setLevel(normalized)
