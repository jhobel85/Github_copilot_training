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

import httpx
from app.clients import InventoryClient, ProductClient
from app.logging_config import add_request_context
from app.main import app
from app.routes import get_inventory_client, get_product_client
from fastapi import FastAPI
from fastapi.testclient import TestClient

client = TestClient(app, headers={"X-API-Key": "test-api-key"})
SERVICE_ROOT = Path(__file__).resolve().parents[1]


class RecordingHttpClient:
    def __init__(self, responses):
        self._responses = iter(responses)
        self.requests = []

    def get(self, url, **kwargs):
        self.requests.append(("GET", url, kwargs))
        return self._next()

    def patch(self, url, **kwargs):
        self.requests.append(("PATCH", url, kwargs))
        return self._next()

    def _next(self):
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


def _json_response(status_code, payload):
    return httpx.Response(status_code, json=payload)


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
                    headers={"X-Request-ID": "order-subprocess"},
                )
                response = urlopen(request, timeout=1)
                break
            except OSError:
                if process.poll() is not None:
                    break
                time.sleep(0.05)
        assert response is not None
        assert response.status == 200
        assert response.headers["X-Request-ID"] == "order-subprocess"
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
            "/orders",
            headers={"X-Request-ID": "order-trace", "X-API-Key": "api-key-secret"},
            json={"customerId": "body-secret"},
        )

    record = next(record for record in _request_log_records(caplog) if record.request_id == "order-trace")
    payload = json.loads(_structured_handler().formatter.format(record))

    assert response.headers["X-Request-ID"] == "order-trace"
    assert payload["request_id"] == "order-trace"
    assert payload["service"] == "order"
    assert payload["method"] == "POST"
    assert payload["path"] == "/orders"
    assert payload["status_code"] == 401
    assert "api-key-secret" not in json.dumps(payload)
    assert "body-secret" not in json.dumps(payload)


def test_concurrent_requests_keep_request_ids_isolated(caplog):
    request_ids = [f"order-concurrent-{index}" for index in range(8)]

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
        if record.request_id.startswith("order-concurrent-")
    }
    assert logged_ids == set(request_ids)


def test_real_uvicorn_stream_contains_only_structured_logs_without_secrets():
    lines = _run_uvicorn_request()
    payloads = [json.loads(line) for line in lines]
    access_payloads = [payload for payload in payloads if payload["logger"] == "uvicorn.access"]

    assert payloads
    assert all(payload["service"] == "order" for payload in payloads)
    assert all(payload["request_id"] in {None, "order-subprocess"} for payload in payloads)
    assert any(payload["logger"] == "uvicorn.error" for payload in payloads)
    assert access_payloads == [
        {
            **access_payloads[0],
            "message": "HTTP request",
            "request_id": "order-subprocess",
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
        raise RuntimeError("private order failure")

    failing_client = TestClient(failing_app, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR):
        response = failing_client.get("/explode", headers={"X-Request-ID": "order-failure"})

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert response.headers["X-Request-ID"] == "order-failure"

    error_record = next(
        record
        for record in caplog.records
        if record.name == "app.request" and record.levelno == logging.ERROR
    )
    payload = json.loads(_structured_handler().formatter.format(error_record))

    assert payload["request_id"] == "order-failure"
    assert payload["status_code"] == 500
    assert payload["exception_type"] == "RuntimeError"
    assert "private order failure" not in response.text


def test_order_forwards_request_id_to_every_upstream_call():
    product_http = RecordingHttpClient([_json_response(200, {"id": "P100", "name": "Mouse", "price": 10.0})])
    inventory_http = RecordingHttpClient(
        [
            _json_response(200, {"productId": "P100", "quantity": 5}),
            _json_response(200, {"productId": "P100", "quantity": 3}),
        ]
    )
    app.dependency_overrides[get_product_client] = lambda: ProductClient(
        http_client=product_http,
        sleep=lambda _: None,
        api_key="upstream-key",
    )
    app.dependency_overrides[get_inventory_client] = lambda: InventoryClient(
        http_client=inventory_http,
        sleep=lambda _: None,
        api_key="upstream-key",
    )

    try:
        response = client.post(
            "/orders",
            headers={"X-Request-ID": "linked-order"},
            json={"customerId": "C101", "productId": "P100", "quantity": 2},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert product_http.requests[0][2]["headers"]["X-Request-ID"] == "linked-order"
    assert inventory_http.requests[0][2]["headers"]["X-Request-ID"] == "linked-order"
    assert inventory_http.requests[1][2]["headers"]["X-Request-ID"] == "linked-order"


def test_order_forwards_request_id_to_every_failed_and_retried_get():
    product_request = httpx.Request("GET", "http://product/products/P100")
    product_http = RecordingHttpClient(
        [
            httpx.ConnectError("first failure", request=product_request),
            _json_response(503, {"detail": "retry"}),
            _json_response(200, {"id": "P100", "name": "Mouse", "price": 10.0}),
        ]
    )
    inventory_request = httpx.Request("GET", "http://inventory/inventory/P100")
    inventory_http = RecordingHttpClient(
        [
            httpx.ConnectError("first failure", request=inventory_request),
            _json_response(503, {"detail": "retry"}),
            _json_response(200, {"productId": "P100", "quantity": 5}),
            _json_response(200, {"productId": "P100", "quantity": 3}),
        ]
    )
    app.dependency_overrides[get_product_client] = lambda: ProductClient(
        http_client=product_http,
        sleep=lambda _: None,
        api_key="upstream-key",
    )
    app.dependency_overrides[get_inventory_client] = lambda: InventoryClient(
        http_client=inventory_http,
        sleep=lambda _: None,
        api_key="upstream-key",
    )

    try:
        response = client.post(
            "/orders",
            headers={"X-Request-ID": "retry-order"},
            json={"customerId": "C101", "productId": "P100", "quantity": 2},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    get_requests = [
        request for request in product_http.requests + inventory_http.requests if request[0] == "GET"
    ]
    assert len(get_requests) == 6
    assert all(request[2]["headers"]["X-Request-ID"] == "retry-order" for request in get_requests)


def test_order_forwards_cancellation_request_id_to_inventory_patch():
    product_http = RecordingHttpClient([_json_response(200, {"id": "P100", "name": "Mouse", "price": 10.0})])
    inventory_http = RecordingHttpClient(
        [
            _json_response(200, {"productId": "P100", "quantity": 5}),
            _json_response(200, {"productId": "P100", "quantity": 3}),
            _json_response(200, {"productId": "P100", "quantity": 5}),
        ]
    )
    app.dependency_overrides[get_product_client] = lambda: ProductClient(
        http_client=product_http,
        sleep=lambda _: None,
        api_key="upstream-key",
    )
    app.dependency_overrides[get_inventory_client] = lambda: InventoryClient(
        http_client=inventory_http,
        sleep=lambda _: None,
        api_key="upstream-key",
    )

    try:
        created = client.post(
            "/orders",
            headers={"X-Request-ID": "creation-order"},
            json={"customerId": "C101", "productId": "P100", "quantity": 2},
        )
        response = client.patch(
            f"/orders/{created.json()['id']}",
            headers={"X-Request-ID": "cancellation-order"},
            json={"status": "CANCELLED"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    patch_requests = [request for request in inventory_http.requests if request[0] == "PATCH"]
    assert patch_requests[-1][2]["headers"]["X-Request-ID"] == "cancellation-order"


def test_existing_error_log_has_request_id_and_json_format(caplog):
    request = httpx.Request("GET", "http://product/products/P100")
    product_http = RecordingHttpClient(
        [
            httpx.ConnectError("first failure", request=request),
            httpx.ConnectError("second failure", request=request),
            httpx.ConnectError("third failure", request=request),
        ]
    )
    app.dependency_overrides[get_product_client] = lambda: ProductClient(
        http_client=product_http,
        sleep=lambda _: None,
    )
    app.dependency_overrides[get_inventory_client] = lambda: InventoryClient(
        http_client=RecordingHttpClient([]),
        sleep=lambda _: None,
    )

    try:
        with caplog.at_level(logging.ERROR):
            response = client.post(
                "/orders",
                headers={"X-Request-ID": "failed-order"},
                json={"customerId": "C101", "productId": "P100", "quantity": 2},
            )
    finally:
        app.dependency_overrides.clear()

    record = next(record for record in caplog.records if record.name == "app.clients")
    payload = json.loads(_structured_handler().formatter.format(record))

    assert response.status_code == 502
    assert record.request_id == "failed-order"
    assert payload["request_id"] == "failed-order"
    assert payload["level"] == "ERROR"
