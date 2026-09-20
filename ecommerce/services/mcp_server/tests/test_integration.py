"""Integration tests exercising the MCP tools against the real Product, Inventory, and Order services."""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from app.main import (
    UpstreamNotFoundProtocolError,
    UpstreamRejectedProtocolError,
    adjust_inventory,
    cancel_order,
    check_inventory,
    create_inventory,
    create_order,
    create_product,
    find_product,
    get_order,
    list_inventory,
    list_orders,
    list_products,
    mcp,
)


@pytest.fixture
def product() -> dict:
    return create_product(name="Wireless Mouse", category="Electronics", price=25.0)


@pytest.fixture
def stocked_product(product: dict) -> dict:
    create_inventory(product["id"], warehouse="WH-EAST", quantity=10)
    return product


def test_create_product_and_find_product_round_trip(product: dict):
    assert find_product(product["id"]) == product


def test_list_products_includes_created_product(product: dict):
    assert any(p["id"] == product["id"] for p in list_products())


def test_list_products_passes_pagination_through():
    create_product(name="Keyboard", category="Electronics", price=75.0)
    create_product(name="Monitor", category="Electronics", price=250.0)
    all_products = list_products(limit=100, offset=0)

    assert list_products(limit=1, offset=1) == all_products[1:2]


def test_products_catalog_resource_includes_created_product(product: dict):
    contents = asyncio.run(mcp.read_resource("products://catalog"))

    assert any(item["id"] == product["id"] for item in json.loads(contents[0].content))


def test_create_inventory_and_check_inventory(product: dict):
    created = create_inventory(product["id"], warehouse="WH-EAST", quantity=10)
    assert created["quantity"] == 10
    assert check_inventory(product["id"]) == created


def test_list_inventory_includes_created_item(stocked_product: dict):
    assert any(item["productId"] == stocked_product["id"] for item in list_inventory())


def test_list_inventory_passes_pagination_through():
    for product_id in (f"P-{uuid.uuid4()}", f"P-{uuid.uuid4()}"):
        create_inventory(product_id, warehouse="WH-EAST", quantity=10)
    all_inventory = list_inventory(limit=100, offset=0)

    assert list_inventory(limit=1, offset=1) == all_inventory[1:2]


def test_adjust_inventory_applies_delta(stocked_product: dict):
    updated = adjust_inventory(stocked_product["id"], quantity_delta=-3)
    assert updated["quantity"] == 7


def test_create_order_reduces_inventory_and_confirms(stocked_product: dict):
    order = create_order("C101", stocked_product["id"], 2)

    assert order["status"] == "CONFIRMED"
    assert order["totalPrice"] == 50.0
    assert check_inventory(stocked_product["id"])["quantity"] == 8


def test_create_order_raises_for_unknown_product():
    with pytest.raises(UpstreamNotFoundProtocolError):
        create_order("C101", f"missing-{uuid.uuid4()}", 1)


def test_create_order_raises_when_inventory_insufficient(stocked_product: dict):
    with pytest.raises(UpstreamRejectedProtocolError):
        create_order("C101", stocked_product["id"], 999)


def test_cancel_order_restores_inventory(stocked_product: dict):
    order = create_order("C101", stocked_product["id"], 2)
    assert check_inventory(stocked_product["id"])["quantity"] == 8

    cancelled = cancel_order(order["id"])

    assert cancelled["status"] == "CANCELLED"
    assert check_inventory(stocked_product["id"])["quantity"] == 10


def test_list_orders_includes_created_order(stocked_product: dict):
    order = create_order("C101", stocked_product["id"], 1)
    assert any(o["id"] == order["id"] for o in list_orders())


def test_list_orders_passes_pagination_through(stocked_product: dict):
    create_order("C201", stocked_product["id"], 1)
    create_order("C202", stocked_product["id"], 1)
    all_orders = list_orders(limit=100, offset=0)

    assert list_orders(limit=1, offset=1) == all_orders[1:2]


def test_get_order_returns_created_order(stocked_product: dict):
    order = create_order("C101", stocked_product["id"], 1)
    assert get_order(order["id"]) == order
