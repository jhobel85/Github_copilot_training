from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx
import pytest
from mcp.shared.exceptions import MCPError

PRODUCT_URL = "http://127.0.0.1:18001"


@contextmanager
def product_service_returning(body: bytes) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_client_session_reads_product_catalog(mcp_client_session) -> None:
    response = httpx.post(
        f"{PRODUCT_URL}/products",
        headers={"X-API-Key": "test-api-key"},
        json={
            "name": "Transport Mouse",
            "description": "Created for the MCP transport test",
            "category": "Electronics",
            "price": 25.0,
        },
    )
    response.raise_for_status()
    product = response.json()

    async def read_catalog() -> list[dict]:
        async with mcp_client_session() as session:
            result = await session.read_resource("products://catalog")
        assert len(result.contents) == 1
        assert result.contents[0].mime_type == "application/json"
        return json.loads(result.contents[0].text)

    assert product in asyncio.run(read_catalog())


def test_client_session_surfaces_missing_product_as_structured_mcp_error(
    mcp_client_session,
) -> None:
    product_id = f"missing-{uuid.uuid4()}"

    async def find_missing_product() -> MCPError:
        async with mcp_client_session() as session:
            with pytest.raises(MCPError) as exc_info:
                await session.call_tool("find_product", {"product_id": product_id})
            return exc_info.value

    error = asyncio.run(find_missing_product())

    assert error.code == -32004
    assert error.data == {
        "type": "upstream_not_found",
        "service": "product",
        "detail": f"Product '{product_id}' not found",
        "status_code": 404,
    }


def test_client_session_surfaces_refused_service_as_structured_mcp_error(
    mcp_client_session,
) -> None:
    async def find_product_while_service_is_down() -> MCPError:
        async with mcp_client_session(product_url="http://127.0.0.1:0") as session:
            with pytest.raises(MCPError) as exc_info:
                await session.call_tool("find_product", {"product_id": "P100"})
            return exc_info.value

    error = asyncio.run(find_product_while_service_is_down())

    assert error.code == -32001
    assert error.data["type"] == "upstream_unavailable"
    assert error.data["service"] == "product"
    assert error.data["status_code"] is None
    assert error.data["detail"].startswith("request failed:")


def test_client_session_surfaces_malformed_success_json_as_upstream_unavailable(
    mcp_client_session,
) -> None:
    async def find_product(product_url: str) -> MCPError:
        async with mcp_client_session(product_url=product_url) as session:
            with pytest.raises(MCPError) as exc_info:
                await session.call_tool("find_product", {"product_id": "P100"})
            return exc_info.value

    with product_service_returning(b"not-json") as product_url:
        error = asyncio.run(find_product(product_url))

    assert error.code == -32001
    assert error.data["type"] == "upstream_unavailable"
    assert error.data["service"] == "product"
    assert error.data["status_code"] is None
    assert "response validation failed" in error.data["detail"]


def test_client_session_surfaces_empty_success_object_as_upstream_unavailable(
    mcp_client_session,
) -> None:
    async def find_product(product_url: str) -> MCPError:
        async with mcp_client_session(product_url=product_url) as session:
            with pytest.raises(MCPError) as exc_info:
                await session.call_tool("find_product", {"product_id": "P100"})
            return exc_info.value

    with product_service_returning(b"{}") as product_url:
        error = asyncio.run(find_product(product_url))

    assert error.code == -32001
    assert error.data["type"] == "upstream_unavailable"
    assert error.data["service"] == "product"
    assert error.data["status_code"] is None
    assert "response validation failed" in error.data["detail"]
