from __future__ import annotations

from typing import Any

import httpx
import pytest
from app.client import EcommerceClient, UpstreamError

VALID_PRODUCT = {
    "id": "P100",
    "name": "Mouse",
    "category": "Electronics",
    "price": 25.0,
    "description": None,
}
VALID_INVENTORY = {
    "productId": "P100",
    "warehouse": "WH-EAST",
    "quantity": 10,
    "lastUpdated": "2026-09-19T08:00:00Z",
}
VALID_ORDER = {
    "id": "O100",
    "customerId": "C100",
    "productId": "P100",
    "quantity": 2,
    "unitPrice": 25.0,
    "totalPrice": 50.0,
    "status": "CONFIRMED",
    "createdAt": "2026-09-19T08:00:00Z",
}


class RecordingHttpClient:
    def __init__(self, response_json: Any = None) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.response_json = [] if response_json is None else response_json

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append((method, url, kwargs))
        return httpx.Response(200, json=self.response_json)


def test_list_products_sends_api_key_and_pagination() -> None:
    http_client = RecordingHttpClient()
    client = EcommerceClient(
        product_url="http://product",
        inventory_url="http://inventory",
        order_url="http://order",
        api_key="mcp-key",
        http_client=http_client,
    )

    client.list_products(limit=25, offset=50)

    assert http_client.calls == [
        (
            "GET",
            "http://product/products",
            {
                "headers": {"X-API-Key": "mcp-key"},
                "params": {"limit": 25, "offset": 50},
            },
        )
    ]


@pytest.mark.parametrize(
    ("method_name", "expected_url"),
    [
        ("list_inventory", "http://inventory/inventory"),
        ("list_orders", "http://order/orders"),
    ],
)
def test_collection_clients_send_api_key_and_pagination(method_name: str, expected_url: str) -> None:
    http_client = RecordingHttpClient()
    client = EcommerceClient(
        product_url="http://product",
        inventory_url="http://inventory",
        order_url="http://order",
        api_key="mcp-key",
        http_client=http_client,
    )

    getattr(client, method_name)(limit=25, offset=50)

    assert http_client.calls == [
        (
            "GET",
            expected_url,
            {
                "headers": {"X-API-Key": "mcp-key"},
                "params": {"limit": 25, "offset": 50},
            },
        )
    ]


def test_not_found_response_preserves_status_and_service() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(404, json={"detail": "Product not found"}, request=request)
    )
    client = EcommerceClient(http_client=httpx.Client(transport=transport))

    with pytest.raises(UpstreamError) as exc_info:
        client.get_product("missing-product")

    assert exc_info.value.service == "product"
    assert exc_info.value.detail == "Product not found"
    assert exc_info.value.status_code == 404


def test_transport_failure_has_no_upstream_status() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = EcommerceClient(http_client=httpx.Client(transport=httpx.MockTransport(fail)))

    with pytest.raises(UpstreamError) as exc_info:
        client.get_product("P100")

    assert exc_info.value.service == "product"
    assert exc_info.value.detail == "request failed: connection refused"
    assert exc_info.value.status_code is None


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json=[]),
        httpx.Response(404, json=["not", "an", "error", "object"]),
    ],
)
def test_malformed_upstream_response_is_reported_as_unavailable(response: httpx.Response) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            response.status_code,
            content=response.content,
            headers=response.headers,
            request=request,
        )
    )
    client = EcommerceClient(http_client=httpx.Client(transport=transport))

    with pytest.raises(UpstreamError, match="response validation failed") as exc_info:
        client.get_product("P100")

    assert exc_info.value.service == "product"
    assert exc_info.value.status_code is None


def test_collection_response_rejects_non_object_items() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=[{"id": "P100"}, "invalid"], request=request)
    )
    client = EcommerceClient(http_client=httpx.Client(transport=transport))

    with pytest.raises(UpstreamError, match="response validation failed") as exc_info:
        client.list_products()

    assert exc_info.value.service == "product"
    assert exc_info.value.status_code is None


@pytest.mark.parametrize(
    ("method_name", "args", "service"),
    [
        ("get_product", ("P100",), "product"),
        ("create_product", ("Mouse", "Electronics", 25.0), "product"),
        ("get_inventory", ("P100",), "inventory"),
        ("create_inventory", ("P100", "WH-EAST", 10), "inventory"),
        ("adjust_inventory", ("P100", 5), "inventory"),
        ("get_order", ("O100",), "order"),
        ("create_order", ("C100", "P100", 2), "order"),
        ("cancel_order", ("O100",), "order"),
    ],
)
def test_single_resource_operations_reject_empty_objects(
    method_name: str,
    args: tuple[Any, ...],
    service: str,
) -> None:
    client = EcommerceClient(http_client=RecordingHttpClient({}))

    with pytest.raises(UpstreamError, match="response validation failed") as exc_info:
        getattr(client, method_name)(*args)

    assert exc_info.value.service == service
    assert exc_info.value.status_code is None


@pytest.mark.parametrize(
    ("method_name", "service"),
    [
        ("list_products", "product"),
        ("list_inventory", "inventory"),
        ("list_orders", "order"),
    ],
)
def test_collection_operations_reject_invalid_resource_items(method_name: str, service: str) -> None:
    client = EcommerceClient(http_client=RecordingHttpClient([{}]))

    with pytest.raises(UpstreamError, match="response validation failed") as exc_info:
        getattr(client, method_name)()

    assert exc_info.value.service == service
    assert exc_info.value.status_code is None


@pytest.mark.parametrize(
    ("method_name", "args", "response_json", "service"),
    [
        ("get_product", ("P100",), {**VALID_PRODUCT, "price": -1}, "product"),
        ("get_inventory", ("P100",), {**VALID_INVENTORY, "quantity": -1}, "inventory"),
        ("get_order", ("O100",), {**VALID_ORDER, "status": "PENDING"}, "order"),
    ],
)
def test_resource_operations_reject_service_specific_invalid_fields(
    method_name: str,
    args: tuple[Any, ...],
    response_json: dict[str, Any],
    service: str,
) -> None:
    client = EcommerceClient(http_client=RecordingHttpClient(response_json))

    with pytest.raises(UpstreamError, match="response validation failed") as exc_info:
        getattr(client, method_name)(*args)

    assert exc_info.value.service == service
    assert exc_info.value.status_code is None


@pytest.mark.parametrize(
    ("method_name", "args", "response_json"),
    [
        ("create_product", ("Mouse", "Electronics", 25.0), VALID_PRODUCT),
        ("list_products", (), [VALID_PRODUCT]),
        ("create_inventory", ("P100", "WH-EAST", 10), VALID_INVENTORY),
        ("adjust_inventory", ("P100", 5), VALID_INVENTORY),
        ("list_inventory", (), [VALID_INVENTORY]),
        ("create_order", ("C100", "P100", 2), VALID_ORDER),
        ("cancel_order", ("O100",), {**VALID_ORDER, "status": "CANCELLED"}),
        ("list_orders", (), [VALID_ORDER]),
    ],
)
def test_mutating_and_collection_operations_preserve_raw_response_shapes(
    method_name: str,
    args: tuple[Any, ...],
    response_json: Any,
) -> None:
    client = EcommerceClient(http_client=RecordingHttpClient(response_json))

    result = getattr(client, method_name)(*args)

    assert result == response_json
    assert type(result) is type(response_json)
