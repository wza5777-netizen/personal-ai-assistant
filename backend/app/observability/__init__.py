"""Observability (structured logging) setup.

Configures structlog to emit single-line JSON logs. A redaction processor
strips sensitive values (password / token / api_key / secret / ...) from every
event dict before it is rendered, so secrets are never written to logs.
"""
import logging
import re

import structlog

from app.config import settings


# Keys whose values must never appear in logs (passwords, tokens, secrets).
_SENSITIVE_RE = re.compile(
    r"|".join(
        [
            "password",
            "token",
            "api[_-]?key",
            "secret",
            "authorization",
            "apikey",
        ]
    ),
    re.IGNORECASE,
)


def _redact_processor(_logger, _method, event_dict: dict) -> dict:
    """Mask values whose key looks sensitive (recursively)."""
    for key, value in list(event_dict.items()):
        if isinstance(key, str) and _SENSITIVE_RE.search(key):
            event_dict[key] = "***REDACTED***"
        elif isinstance(value, dict):
            event_dict[key] = _redact_processor(_logger, _method, dict(value))
    return event_dict


def configure_logging() -> None:
    """Configure structlog with JSON output + sensitive-value redaction."""
    level = logging.INFO
    if settings is not None and getattr(settings, "log_level", None):
        level = logging.getLevelName(str(settings.log_level).upper())

    logging.basicConfig(format="%(message)s", level=level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


logger = structlog.get_logger()
