"""Synchronous HTTP client wrapping the Product, Inventory, and Order services."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError

from app.config import (
    API_KEY,
    INVENTORY_SERVICE_URL,
    ORDER_SERVICE_URL,
    PRODUCT_SERVICE_URL,
    REQUEST_TIMEOUT_SECONDS,
)
from app.models import InventoryResponse, OrderResponse, ProductResponse

PRODUCT_RESPONSE = TypeAdapter(ProductResponse)
PRODUCT_COLLECTION_RESPONSE = TypeAdapter(list[ProductResponse])
INVENTORY_RESPONSE = TypeAdapter(InventoryResponse)
INVENTORY_COLLECTION_RESPONSE = TypeAdapter(list[InventoryResponse])
ORDER_RESPONSE = TypeAdapter(OrderResponse)
ORDER_COLLECTION_RESPONSE = TypeAdapter(list[OrderResponse])


class UpstreamError(Exception):
    """Raised when a downstream service call fails or returns an unexpected status."""

    def __init__(self, service: str, detail: str, status_code: int | None = None) -> None:
        self.service = service
        self.detail = detail
        self.status_code = status_code
        super().__init__(f"{service} service error: {detail}")


class EcommerceClient:
    """Thin synchronous HTTP client over the three e-commerce REST services."""

    def __init__(
        self,
        product_url: str = PRODUCT_SERVICE_URL,
        inventory_url: str = INVENTORY_SERVICE_URL,
        order_url: str = ORDER_SERVICE_URL,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
        api_key: str = API_KEY,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._product_url = product_url
        self._inventory_url = inventory_url
        self._order_url = order_url
        self._api_key = api_key
        self._client = http_client or httpx.Client(timeout=timeout)

    def _request(
        self,
        service: str,
        method: str,
        url: str,
        response_schema: TypeAdapter[Any],
        **kwargs: Any,
    ) -> Any:
        headers = {"X-API-Key": self._api_key, **kwargs.pop("headers", {})}
        try:
            response = self._client.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise UpstreamError(service, f"request failed: {exc}") from exc

        if response.status_code >= 400:
            try:
                error_payload = response.json()
            except ValueError:
                raise UpstreamError(service, "response validation failed: invalid JSON") from None
            if not isinstance(error_payload, dict):
                raise UpstreamError(
                    service,
                    "response validation failed: error payload must be an object",
                )
            detail = error_payload.get("detail", response.text)
            raise UpstreamError(service, str(detail), status_code=response.status_code)

        if response.status_code == 204 or not response.content:
            return None
        try:
            payload = response.json()
        except ValueError:
            raise UpstreamError(service, "response validation failed: invalid JSON") from None
        try:
            response_schema.validate_python(payload)
        except ValidationError as exc:
            raise UpstreamError(service, f"response validation failed: {exc}") from None
        return payload

    # Products
    def list_products(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return self._request(
            "product",
            "GET",
            f"{self._product_url}/products",
            PRODUCT_COLLECTION_RESPONSE,
            params={"limit": limit, "offset": offset},
        )

    def get_product(self, product_id: str) -> dict[str, Any]:
        return self._request(
            "product",
            "GET",
            f"{self._product_url}/products/{product_id}",
            PRODUCT_RESPONSE,
        )

    def create_product(
        self, name: str, category: str, price: float, description: str | None = None
    ) -> dict[str, Any]:
        payload = {"name": name, "category": category, "price": price, "description": description}
        return self._request(
            "product",
            "POST",
            f"{self._product_url}/products",
            PRODUCT_RESPONSE,
            json=payload,
        )

    # Inventory
    def list_inventory(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return self._request(
            "inventory",
            "GET",
            f"{self._inventory_url}/inventory",
            INVENTORY_COLLECTION_RESPONSE,
            params={"limit": limit, "offset": offset},
        )

    def get_inventory(self, product_id: str) -> dict[str, Any]:
        return self._request(
            "inventory",
            "GET",
            f"{self._inventory_url}/inventory/{product_id}",
            INVENTORY_RESPONSE,
        )

    def create_inventory(self, product_id: str, warehouse: str, quantity: int) -> dict[str, Any]:
        payload = {"productId": product_id, "warehouse": warehouse, "quantity": quantity}
        return self._request(
            "inventory",
            "POST",
            f"{self._inventory_url}/inventory",
            INVENTORY_RESPONSE,
            json=payload,
        )

    def adjust_inventory(
        self,
        product_id: str,
        quantity: int | None = None,
        quantity_delta: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if quantity is not None:
            payload["quantity"] = quantity
        if quantity_delta is not None:
            payload["quantityDelta"] = quantity_delta
        return self._request(
            "inventory",
            "PATCH",
            f"{self._inventory_url}/inventory/{product_id}",
            INVENTORY_RESPONSE,
            json=payload,
        )

    # Orders
    def list_orders(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return self._request(
            "order",
            "GET",
            f"{self._order_url}/orders",
            ORDER_COLLECTION_RESPONSE,
            params={"limit": limit, "offset": offset},
        )

    def get_order(self, order_id: str) -> dict[str, Any]:
        return self._request("order", "GET", f"{self._order_url}/orders/{order_id}", ORDER_RESPONSE)

    def create_order(self, customer_id: str, product_id: str, quantity: int) -> dict[str, Any]:
        payload = {"customerId": customer_id, "productId": product_id, "quantity": quantity}
        return self._request(
            "order",
            "POST",
            f"{self._order_url}/orders",
            ORDER_RESPONSE,
            json=payload,
        )

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        return self._request(
            "order",
            "PATCH",
            f"{self._order_url}/orders/{order_id}",
            ORDER_RESPONSE,
            json={"status": "CANCELLED"},
        )


# Singleton so requests reuse pooled httpx connections instead of opening one per call.
ecommerce_client = EcommerceClient()
