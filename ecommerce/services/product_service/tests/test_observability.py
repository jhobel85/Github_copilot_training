import json
import logging
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import UUID

from app.logging_config import add_request_context
from app.main import app
from fastapi import FastAPI
from fastapi.testclient import TestClient

client = TestClient(app, headers={"X-API-Key": "test-api-key"})
SERVICE_ROOT = Path(__file__).resolve().parents[1]


def _request_log_records(caplog):
    return [record for record in caplog.records if record.name == "app.request"]


def _structured_handler():
    return next(
        handler for handler in logging.getLogger().handlers if getattr(handler, "_structured_json", False)
    )


def _free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _run_uvicorn_request():
    port = _free_port()
    environment = os.environ.copy()
    environment["API_KEY"] = "test-api-key"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=SERVICE_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    response = None
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                request = Request(
                    f"http://127.0.0.1:{port}/health?token=stream-secret",
                    headers={"X-Request-ID": "product-subprocess"},
                )
                response = urlopen(request, timeout=1)
                break
            except OSError:
                if process.poll() is not None:
                    break
                time.sleep(0.05)
        assert response is not None
        assert response.status == 200
        assert response.headers["X-Request-ID"] == "product-subprocess"
    finally:
        if response is not None:
            response.close()
        process.terminate()
        stdout, stderr = process.communicate(timeout=10)
    return [line for line in (stdout + stderr).splitlines() if line]


def test_request_id_is_generated_returned_and_logged(caplog):
    with caplog.at_level(logging.INFO):
        response = client.get("/health")

    request_id = response.headers["X-Request-ID"]
    UUID(request_id)
    assert any(record.request_id == request_id for record in _request_log_records(caplog))


def test_supplied_request_id_is_returned_in_structured_log_without_secrets(caplog):
    with caplog.at_level(logging.INFO):
        response = client.post(
            "/products",
            headers={"X-Request-ID": "product-trace", "X-API-Key": "api-key-secret"},
            json={
                "name": "body-secret",
                "category": "Electronics",
                "price": 10,
            },
        )

    record = next(record for record in _request_log_records(caplog) if record.request_id == "product-trace")
    payload = json.loads(_structured_handler().formatter.format(record))

    assert response.headers["X-Request-ID"] == "product-trace"
    assert payload["request_id"] == "product-trace"
    assert payload["service"] == "product"
    assert payload["method"] == "POST"
    assert payload["path"] == "/products"
    assert payload["status_code"] == 401
    assert "api-key-secret" not in json.dumps(payload)
    assert "body-secret" not in json.dumps(payload)


def test_concurrent_requests_keep_request_ids_isolated(caplog):
    request_ids = [f"product-concurrent-{index}" for index in range(8)]

    with caplog.at_level(logging.INFO), ThreadPoolExecutor(max_workers=len(request_ids)) as executor:
        responses = list(
            executor.map(
                lambda request_id: client.get("/health", headers={"X-Request-ID": request_id}),
                request_ids,
            )
        )

    assert [response.headers["X-Request-ID"] for response in responses] == request_ids
    logged_ids = {
        record.request_id
        for record in _request_log_records(caplog)
        if record.request_id.startswith("product-concurrent-")
    }
    assert logged_ids == set(request_ids)


def test_real_uvicorn_stream_contains_only_structured_logs_without_secrets():
    lines = _run_uvicorn_request()
    payloads = [json.loads(line) for line in lines]
    access_payloads = [payload for payload in payloads if payload["logger"] == "uvicorn.access"]

    assert payloads
    assert all(payload["service"] == "product" for payload in payloads)
    assert all(payload["request_id"] in {None, "product-subprocess"} for payload in payloads)
    assert any(payload["logger"] == "uvicorn.error" for payload in payloads)
    assert access_payloads == [
        {
            **access_payloads[0],
            "message": "HTTP request",
            "request_id": "product-subprocess",
            "method": "GET",
            "path": "/health",
            "status_code": 200,
        }
    ]
    assert "stream-secret" not in "\n".join(lines)


def test_unhandled_exception_returns_and_logs_request_id(caplog):
    failing_app = FastAPI()
    add_request_context(failing_app)

    @failing_app.get("/explode")
    def explode() -> None:
        raise RuntimeError("private product failure")

    failing_client = TestClient(failing_app, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR):
        response = failing_client.get("/explode", headers={"X-Request-ID": "product-failure"})

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert response.headers["X-Request-ID"] == "product-failure"

    error_record = next(
        record
        for record in caplog.records
        if record.name == "app.request" and record.levelno == logging.ERROR
    )
    payload = json.loads(_structured_handler().formatter.format(error_record))

    assert payload["request_id"] == "product-failure"
    assert payload["status_code"] == 500
    assert payload["exception_type"] == "RuntimeError"
    assert "private product failure" not in response.text
