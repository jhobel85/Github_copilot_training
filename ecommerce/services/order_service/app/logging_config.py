"""Structured logging and request correlation for the Order Service."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, Request
from starlette.datastructures import MutableHeaders
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SERVICE_NAME = "order"
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "service": SERVICE_NAME,
            "logger": record.name,
            "message": self._message(record),
            "request_id": getattr(record, "request_id", None),
        }
        for field in ("method", "path", "status_code"):
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info is not None:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=True)

    @staticmethod
    def _message(record: logging.LogRecord) -> str:
        if record.name == "uvicorn.access" and isinstance(record.args, tuple) and len(record.args) == 5:
            _, method, target, _, status_code = record.args
            record.method = method
            record.path = urlsplit(str(target)).path
            record.status_code = status_code
            return "HTTP request"
        return record.getMessage()


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


class JsonStreamHandler(logging.StreamHandler):
    _structured_json = True


def configure_logging() -> None:
    handler = JsonStreamHandler()
    handler.addFilter(RequestContextFilter())
    handler.setFormatter(JsonFormatter())
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True


def get_request_id() -> str | None:
    return _request_id.get()


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        token: Token[str | None] = _request_id.set(request_id)
        status_code = 500
        response_started = False
        request_logger = logging.getLogger("app.request")

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started, status_code
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            request_logger.exception(
                "Unhandled application exception",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                },
            )
            if response_started:
                raise
            response = PlainTextResponse(
                "Internal Server Error",
                status_code=status_code,
                headers={"X-Request-ID": request_id},
            )
            await response(scope, receive, send_with_request_id)
        finally:
            request_logger.info(
                "Request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                },
            )
            _request_id.reset(token)


def add_request_context(app: FastAPI) -> None:
    app.add_middleware(RequestContextMiddleware)
