"""MCP server exposing the Product, Inventory, and Order services as tools."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError

from app.client import UpstreamError, ecommerce_client

mcp = MCPServer("ecommerce")

UPSTREAM_REJECTED = -32000
UPSTREAM_UNAVAILABLE = -32001
UPSTREAM_NOT_FOUND = -32004


class UpstreamProtocolError(MCPError):
    """Structured MCP error for an anticipated upstream service failure."""

    error_type = "upstream_error"
    error_code = UPSTREAM_REJECTED

    def __init__(self, error: UpstreamError) -> None:
        super().__init__(
            code=self.error_code,
            message=f"{error.service} service error: {error.detail}",
            data={
                "type": self.error_type,
                "service": error.service,
                "detail": error.detail,
                "status_code": error.status_code,
            },
        )


class UpstreamNotFoundProtocolError(UpstreamProtocolError):
    """An upstream resource named by the caller does not exist."""

    error_type = "upstream_not_found"
    error_code = UPSTREAM_NOT_FOUND


class UpstreamUnavailableProtocolError(UpstreamProtocolError):
    """An upstream service could not be reached or returned a server error."""

    error_type = "upstream_unavailable"
    error_code = UPSTREAM_UNAVAILABLE


class UpstreamRejectedProtocolError(UpstreamProtocolError):
    """An upstream service rejected the request for another client-side reason."""

    error_type = "upstream_rejected"


def _protocol_error(error: UpstreamError) -> UpstreamProtocolError:
    if error.status_code == 404:
        return UpstreamNotFoundProtocolError(error)
    if error.status_code is None or error.status_code >= 500:
        return UpstreamUnavailableProtocolError(error)
    return UpstreamRejectedProtocolError(error)


def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except UpstreamError as exc:
        raise _protocol_error(exc) from exc


@mcp.resource(
    "products://catalog",
    name="product_catalog",
    description="Complete read-only product catalog.",
    mime_type="application/json",
)
def product_catalog() -> list[dict[str, Any]]:
    """Load the complete product catalog through the authenticated paginated client."""
    page_size = 100
    offset = 0
    products: list[dict[str, Any]] = []
    while True:
        page = _call(ecommerce_client.list_products, limit=page_size, offset=offset)
        products.extend(page)
        if len(page) < page_size:
            return products
        offset += page_size


@mcp.tool()
def list_products(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """List products with a page size of 1-100 and a zero-based offset."""
    return _call(ecommerce_client.list_products, limit=limit, offset=offset)


@mcp.tool()
def find_product(product_id: str) -> dict[str, Any]:
    """Look up a single product by its id."""
    return _call(ecommerce_client.get_product, product_id)


@mcp.tool()
def create_product(name: str, category: str, price: float, description: str | None = None) -> dict[str, Any]:
    """Create a new product."""
    return _call(ecommerce_client.create_product, name, category, price, description)


@mcp.tool()
def list_inventory(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """List inventory levels with a page size of 1-100 and a zero-based offset."""
    return _call(ecommerce_client.list_inventory, limit=limit, offset=offset)


@mcp.tool()
def check_inventory(product_id: str) -> dict[str, Any]:
    """Check the current stock level for a product."""
    return _call(ecommerce_client.get_inventory, product_id)


@mcp.tool()
def create_inventory(product_id: str, warehouse: str, quantity: int) -> dict[str, Any]:
    """Register initial inventory for a product."""
    return _call(ecommerce_client.create_inventory, product_id, warehouse, quantity)


@mcp.tool()
def adjust_inventory(
    product_id: str, quantity: int | None = None, quantity_delta: int | None = None
) -> dict[str, Any]:
    """Set an absolute quantity or apply a relative quantity_delta for a product (not both)."""
    return _call(ecommerce_client.adjust_inventory, product_id, quantity, quantity_delta)


@mcp.tool()
def list_orders(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """List orders with a page size of 1-100 and a zero-based offset."""
    return _call(ecommerce_client.list_orders, limit=limit, offset=offset)


@mcp.tool()
def get_order(order_id: str) -> dict[str, Any]:
    """Look up a single order by its id."""
    return _call(ecommerce_client.get_order, order_id)


@mcp.tool()
def create_order(customer_id: str, product_id: str, quantity: int) -> dict[str, Any]:
    """Place an order: validates the product, checks and reduces inventory, and returns the confirmation."""
    return _call(ecommerce_client.create_order, customer_id, product_id, quantity)


@mcp.tool()
def cancel_order(order_id: str) -> dict[str, Any]:
    """Cancel an existing order and restore its quantity back to inventory."""
    return _call(ecommerce_client.cancel_order, order_id)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
