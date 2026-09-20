from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from app.client import UpstreamError
from app.main import mcp
from mcp.shared.exceptions import MCPError


def upstream_error(service: str, detail: str, status_code: int | None = None) -> UpstreamError:
    error = UpstreamError(service, detail)
    error.status_code = status_code
    return error


class StubEcommerceClient:
    def __init__(
        self,
        *,
        product_pages: dict[int, list[dict[str, Any]]] | None = None,
        get_product_error: UpstreamError | None = None,
    ) -> None:
        self.product_pages = product_pages or {}
        self.get_product_error = get_product_error
        self.list_products_calls: list[tuple[int, int]] = []

    def list_products(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        self.list_products_calls.append((limit, offset))
        return self.product_pages.get(offset, [])

    def get_product(self, product_id: str) -> dict[str, Any]:
        if self.get_product_error is not None:
            raise self.get_product_error
        return {"id": product_id}


def test_products_catalog_resource_reads_every_page(monkeypatch: pytest.MonkeyPatch) -> None:
    first_page = [{"id": f"P{index:03}"} for index in range(100)]
    final_page = [{"id": "P100"}]
    client = StubEcommerceClient(product_pages={0: first_page, 100: final_page})
    monkeypatch.setattr("app.main.ecommerce_client", client)

    resources = asyncio.run(mcp.list_resources())
    contents = asyncio.run(mcp.read_resource("products://catalog"))

    catalog = next(resource for resource in resources if str(resource.uri) == "products://catalog")
    assert catalog.mime_type == "application/json"
    assert json.loads(contents[0].content) == [*first_page, *final_page]
    assert client.list_products_calls == [(100, 0), (100, 100)]


@pytest.mark.parametrize(
    ("upstream_error", "expected_type", "expected_class_name"),
    [
        (
            upstream_error("product", "Product not found", status_code=404),
            "upstream_not_found",
            "UpstreamNotFoundProtocolError",
        ),
        (
            upstream_error("product", "request failed: connection refused"),
            "upstream_unavailable",
            "UpstreamUnavailableProtocolError",
        ),
    ],
)
def test_tool_errors_preserve_machine_readable_upstream_kind(
    monkeypatch: pytest.MonkeyPatch,
    upstream_error: UpstreamError,
    expected_type: str,
    expected_class_name: str,
) -> None:
    client = StubEcommerceClient(get_product_error=upstream_error)
    monkeypatch.setattr("app.main.ecommerce_client", client)

    with pytest.raises(MCPError) as exc_info:
        asyncio.run(mcp.call_tool("find_product", {"product_id": "missing-product"}))

    assert type(exc_info.value).__name__ == expected_class_name
    assert exc_info.value.data == {
        "type": expected_type,
        "service": "product",
        "detail": upstream_error.detail,
        "status_code": upstream_error.status_code,
    }
