"""Production error-handling layer for FastAPI.

Provides:
  * A :class:`RequestIDMiddleware` that assigns a unique ``request_id`` (UUID)
    to every request, exposes it via the ``X-Request-ID`` response header, and
    makes it available through :func:`get_request_id` for structured logging.
  * A uniform error response schema (``{"error": {...}}``) so that clients
    never receive tracebacks, SQL errors, API keys, or internal file paths.
  * Exception handlers for ``Exception``, ``RequestValidationError`` and
    ``StarletteHTTPException``.

This layer is intentionally non-invasive: it does NOT touch the LangGraph
runtime, the memory/RAG stack, the tool gateway, or the streaming logic. Agents
keep emitting their own structured error events; the handlers below only cover
the standard (non-streaming) HTTP surface.
"""
from __future__ import annotations

import contextvars
import traceback
import uuid
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.observability import logger

# ---------------------------------------------------------------------------
# Request ID context (available to any coroutine serving the request)
# ---------------------------------------------------------------------------
_request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


def get_request_id(request: Request | None = None) -> str | None:
    """Return the current request id.

    Prefers the value stashed on the ASGI scope (set by
    :class:`RequestIDMiddleware`) so it is available inside exception handlers
    regardless of coroutine context boundaries, and falls back to the
    contextvar used for structured logging.
    """
    if request is not None:
        rid = request.scope.get("state", {}).get("request_id")
        if rid:
            return rid
    return _request_id_var.get()


class RequestIDMiddleware:
    """Attach a UUID to every request and echo it back via ``X-Request-ID``."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex
        # Stash on the ASGI scope so exception handlers (which receive a
        # ``Request`` backed by this same scope) can read it reliably even if
        # the coroutine context is re-spawned downstream.
        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id
        token = _request_id_var.set(request_id)
        try:
            # Inject the header into the response by wrapping ``send``.
            async def send_wrapper(message: dict) -> None:
                if message["type"] == "http.response.start":
                    headers = message.setdefault("headers", [])
                    # Avoid duplicate headers.
                    if not any(h[0] == b"x-request-id" for h in headers):
                        headers.append(
                            (b"x-request-id", request_id.encode("ascii"))
                        )
                await send(message)

            await self.app(scope, receive, send_wrapper)
        finally:
            _request_id_var.reset(token)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _is_debug() -> bool:
    return bool(getattr(settings, "debug", False))


def _safe_message(exc: Exception, *, fallback: str) -> str:
    """Return a client-safe message.

    In debug mode we surface the original message (useful in development).
    In production we never leak the raw exception text, which may contain
    SQL fragments, file paths, or secrets.
    """
    if _is_debug():
        return str(exc) or fallback
    return fallback


def _build_error_response(
    *,
    code: str,
    message: str,
    status_code: int,
    request_id: str | None,
) -> JSONResponse:
    body = {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
        }
    }
    response = JSONResponse(status_code=status_code, content=body)
    # Mirror the request id in a response header. We set it explicitly here
    # (not only via the middleware's send wrapper) because 5xx responses can
    # be emitted by Starlette's ServerErrorMiddleware outside our wrapper.
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------
async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Catch-all for any unexpected server error.

    The full traceback is logged server-side (correlated by request_id) but is
    NEVER returned to the client.
    """
    request_id = get_request_id(request)
    logger.error(
        "unhandled_exception",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        error_type=type(exc).__name__,
        error=str(exc),
        traceback=traceback.format_exc(),
    )
    return _build_error_response(
        code="internal_error",
        message=_safe_message(
            exc, fallback="An unexpected error occurred. Please try again later."
        ),
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        request_id=request_id,
    )


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Handle FastAPI/Starlette HTTP exceptions (404, 401, 403, ...).

    ``exc.detail`` is generally safe (no SQL/paths) but we only forward it when
    it is a plain string to avoid leaking structured internals.
    """
    request_id = get_request_id(request)
    detail = exc.detail if isinstance(exc.detail, str) else None
    message = detail or _http_code_phrase(exc.status_code)
    logger.info(
        "http_exception",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status_code=exc.status_code,
        error_type=type(exc).__name__,
    )
    return _build_error_response(
        code=_http_code_phrase(exc.status_code, as_code=True),
        message=message,
        status_code=exc.status_code,
        request_id=request_id,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle pydantic request validation errors (422).

    We return a generic validation message plus a sanitized field list. We do
    NOT echo the raw pydantic error context, which can reference internal
    schemas/paths.
    """
    request_id = get_request_id(request)
    fields = [
        ".".join(str(loc) for loc in err.get("loc", []))
        for err in exc.errors()
        if isinstance(err, dict) and err.get("loc")
    ]
    logger.info(
        "validation_error",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        fields=fields,
    )
    return _build_error_response(
        code="validation_error",
        message=_safe_message(
            exc, fallback="Request validation failed. Check the provided fields."
        ),
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        request_id=request_id,
    )


def _http_code_phrase(code: int, *, as_code: bool = False) -> str:
    """Map an HTTP status code to a stable phrase / error code string."""
    phrases = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        408: "request_timeout",
        409: "conflict",
        413: "payload_too_large",
        422: "validation_error",
        429: "too_many_requests",
        500: "internal_error",
        502: "bad_gateway",
        503: "service_unavailable",
        504: "gateway_timeout",
    }
    if as_code:
        return phrases.get(code, f"http_{code}")
    return phrases.get(code, "error").replace("_", " ").title()


def register_error_handling(app: FastAPI) -> None:
    """Wire the middleware and exception handlers into the FastAPI app."""
    app.add_middleware(RequestIDMiddleware)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
