from __future__ import annotations

from contextvars import ContextVar, Token
from datetime import UTC, datetime
import json
import logging
from logging.config import dictConfig


_REQUEST_ID_CTX: ContextVar[str] = ContextVar("studyhub_request_id", default="-")


def bind_request_id(request_id: str) -> Token[str]:
    return _REQUEST_ID_CTX.set(request_id)


def reset_request_id(token: Token[str]) -> None:
    _REQUEST_ID_CTX.reset(token)


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _REQUEST_ID_CTX.get("-")
        return True


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
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "requestId": getattr(record, "request_id", "-"),
        }
        for field_name in self.EXTRA_FIELDS:
            value = getattr(record, field_name, None)
            if value is not None:
                payload[field_name] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str, *, log_format: str = "text", access_log_enabled: bool = True) -> None:
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
