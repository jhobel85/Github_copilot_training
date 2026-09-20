from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from uuid import UUID

import httpx
import pytest
from app.clients import (
    InsufficientInventoryError,
    InventoryClient,
    InventoryIdempotencyConflictError,
    ProductClient,
    UpstreamNotFoundError,
    UpstreamUnavailableError,
)
from app.db import OrderIdempotencyClaimORM, session_scope
from app.main import app
from app.models import Order, UpstreamInventory, UpstreamProduct
from app.routes import get_inventory_client, get_product_client
from app.storage import order_repository
from fastapi.testclient import TestClient

client = TestClient(app, headers={"X-API-Key": "test-api-key"})
unauthenticated_client = TestClient(app)


class SequencedHttpClient:
    def __init__(self, outcomes: list[httpx.Response | Exception]):
        self._outcomes = iter(outcomes)
        self.get_calls = 0
        self.patch_calls = 0
        self.get_kwargs: list[dict] = []
        self.patch_kwargs: list[dict] = []

    def get(self, url: str, **kwargs) -> httpx.Response:
        self.get_calls += 1
        self.get_kwargs.append(kwargs)
        return self._next()

    def patch(self, url: str, **kwargs) -> httpx.Response:
        self.patch_calls += 1
        self.patch_kwargs.append(kwargs)
        return self._next()

    def _next(self) -> httpx.Response:
        outcome = next(self._outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def json_response(status_code: int, payload: dict) -> httpx.Response:
    return httpx.Response(status_code, json=payload)


class FakeProductClient:
    def __init__(self, products: dict | None = None, error: Exception | None = None):
        self._products = products or {}
        self._error = error

    def get_product(self, product_id: str) -> UpstreamProduct:
        if self._error:
            raise self._error
        if product_id not in self._products:
            raise UpstreamNotFoundError(f"Product '{product_id}' not found")
        return UpstreamProduct.model_validate(self._products[product_id])


class FakeInventoryClient:
    def __init__(
        self,
        inventory: dict | None = None,
        error: Exception | None = None,
        reduce_error: Exception | None = None,
    ):
        self._inventory = inventory or {}
        self._error = error
        self._reduce_error = reduce_error
        self.reduced: tuple[str, int] | None = None
        self.restored: tuple[str, int] | None = None
        self.reduction_keys: list[str | None] = []
        self.restore_keys: list[str | None] = []
        self._applied_keys: set[str] = set()

    def get_inventory(self, product_id: str) -> UpstreamInventory:
        if self._error:
            raise self._error
        if product_id not in self._inventory:
            raise UpstreamNotFoundError(f"Inventory for product '{product_id}' not found")
        return UpstreamInventory.model_validate(self._inventory[product_id])

    def reduce_inventory(self, product_id: str, quantity: int, idempotency_key: str | None = None) -> None:
        self._adjust(quantity)
        self.reduction_keys.append(idempotency_key)
        if idempotency_key is not None and idempotency_key in self._applied_keys:
            return
        self._inventory[product_id]["quantity"] -= quantity
        if idempotency_key is not None:
            self._applied_keys.add(idempotency_key)
        self.reduced = (product_id, quantity)

    def restore_inventory(self, product_id: str, quantity: int, idempotency_key: str | None = None) -> None:
        self._adjust(quantity)
        self.restore_keys.append(idempotency_key)
        if idempotency_key is not None and idempotency_key in self._applied_keys:
            return
        self._inventory[product_id]["quantity"] += quantity
        if idempotency_key is not None:
            self._applied_keys.add(idempotency_key)
        self.restored = (product_id, quantity)

    def _adjust(self, quantity: int) -> None:
        if self._reduce_error:
            raise self._reduce_error
        if self._error:
            raise self._error


@pytest.fixture(autouse=True)
def reset_repository():
    order_repository.clear()
    yield
    order_repository.clear()
    app.dependency_overrides.clear()


def override_clients(product_client, inventory_client):
    app.dependency_overrides[get_product_client] = lambda: product_client
    app.dependency_overrides[get_inventory_client] = lambda: inventory_client


def sample_payload(**overrides):
    payload = {"customerId": "C101", "productId": "P100", "quantity": 2}
    payload.update(overrides)
    return payload


def sample_order(order_id: str) -> Order:
    return Order(
        id=order_id,
        customerId="C101",
        productId="P100",
        quantity=2,
        unitPrice=10.0,
        totalPrice=20.0,
        status="CONFIRMED",
        createdAt=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_product_get_retries_request_failures_with_bounded_exponential_backoff():
    request = httpx.Request("GET", "http://product/products/P100")
    http_client = SequencedHttpClient(
        [
            httpx.ConnectError("first failure", request=request),
            httpx.ReadTimeout("second failure", request=request),
            json_response(200, {"id": "P100", "price": 10.0}),
        ]
    )
    delays: list[float] = []

    product = ProductClient(http_client=http_client, sleep=delays.append).get_product("P100")

    assert product.id == "P100"
    assert product.price == 10.0
    assert http_client.get_calls == 3
    assert delays == [0.1, 0.2]


def test_product_client_sends_api_key():
    http_client = SequencedHttpClient([json_response(200, {"id": "P100", "price": 10.0})])

    ProductClient(http_client=http_client, sleep=lambda _: None, api_key="upstream-key").get_product("P100")

    assert http_client.get_kwargs == [{"headers": {"X-API-Key": "upstream-key"}}]


def test_inventory_get_retries_server_errors_then_succeeds():
    http_client = SequencedHttpClient(
        [
            json_response(503, {"detail": "unavailable"}),
            json_response(502, {"detail": "bad gateway"}),
            json_response(200, {"productId": "P100", "quantity": 5}),
        ]
    )

    inventory = InventoryClient(http_client=http_client, sleep=lambda _: None).get_inventory("P100")

    assert inventory.productId == "P100"
    assert inventory.quantity == 5
    assert http_client.get_calls == 3


def test_inventory_patch_is_retried_once_with_same_key_after_transport_failure():
    request = httpx.Request("PATCH", "http://inventory/inventory/P100")
    http_client = SequencedHttpClient(
        [
            httpx.ReadTimeout("ambiguous outcome", request=request),
            json_response(200, {"productId": "P100", "quantity": 3}),
        ]
    )
    delays: list[float] = []

    InventoryClient(http_client=http_client, sleep=delays.append).reduce_inventory("P100", 2, "order-key")

    assert http_client.patch_calls == 2
    sent_keys = [kwargs["headers"]["Idempotency-Key"] for kwargs in http_client.patch_kwargs]
    assert sent_keys == ["order-key", "order-key"]
    assert delays == [0.1]


def test_inventory_patch_raises_unavailable_after_retried_transport_failure():
    request = httpx.Request("PATCH", "http://inventory/inventory/P100")
    http_client = SequencedHttpClient(
        [
            httpx.ConnectError("connection refused", request=request),
            httpx.ReadError("connection reset", request=request),
        ]
    )

    with pytest.raises(UpstreamUnavailableError, match="request failed"):
        InventoryClient(http_client=http_client, sleep=lambda _: None).reduce_inventory(
            "P100", 2, "order-key"
        )

    assert http_client.patch_calls == 2


def test_inventory_patch_is_single_attempt_without_idempotency_key():
    request = httpx.Request("PATCH", "http://inventory/inventory/P100")
    http_client = SequencedHttpClient(
        [
            httpx.ReadTimeout("ambiguous outcome", request=request),
            json_response(200, {"productId": "P100", "quantity": 3}),
        ]
    )

    with pytest.raises(UpstreamUnavailableError, match="timed out"):
        InventoryClient(http_client=http_client, sleep=lambda _: None).reduce_inventory("P100", 2)

    assert http_client.patch_calls == 1


def test_inventory_patch_is_not_retried_on_5xx_response():
    http_client = SequencedHttpClient(
        [
            json_response(503, {"detail": "upstream unavailable"}),
            json_response(200, {"productId": "P100", "quantity": 3}),
        ]
    )

    with pytest.raises(UpstreamUnavailableError, match="returned 503"):
        InventoryClient(http_client=http_client, sleep=lambda _: None).reduce_inventory(
            "P100", 2, "order-key"
        )

    assert http_client.patch_calls == 1


def test_inventory_client_sends_api_key_with_idempotency_key():
    http_client = SequencedHttpClient([json_response(200, {"productId": "P100", "quantity": 3})])

    InventoryClient(
        http_client=http_client,
        sleep=lambda _: None,
        api_key="upstream-key",
    ).reduce_inventory("P100", 2, "order-key")

    assert http_client.patch_kwargs == [
        {
            "json": {"quantityDelta": -2},
            "headers": {
                "X-API-Key": "upstream-key",
                "Idempotency-Key": "order-key",
            },
        }
    ]


@pytest.mark.parametrize(
    ("upstream_client", "payload"),
    [
        (ProductClient, {"id": "P100", "price": "not-a-price"}),
        (InventoryClient, {"productId": "P100", "quantity": "not-a-quantity"}),
    ],
)
def test_get_rejects_malformed_upstream_payload_with_validation_detail(upstream_client, payload):
    http_client = SequencedHttpClient([json_response(200, payload)])

    with pytest.raises(UpstreamUnavailableError, match="validation failed"):
        upstream_client(http_client=http_client, sleep=lambda _: None).get_product(
            "P100"
        ) if upstream_client is ProductClient else upstream_client(
            http_client=http_client, sleep=lambda _: None
        ).get_inventory("P100")


@pytest.mark.parametrize(
    ("upstream_client", "payload"),
    [
        (ProductClient, {"id": "P999", "price": 10.0}),
        (InventoryClient, {"productId": "P999", "quantity": 5}),
    ],
)
def test_get_rejects_upstream_payload_for_a_different_product(upstream_client, payload):
    http_client = SequencedHttpClient([json_response(200, payload)])

    with pytest.raises(UpstreamUnavailableError, match="identifier mismatch"):
        upstream_client(http_client=http_client, sleep=lambda _: None).get_product(
            "P100"
        ) if upstream_client is ProductClient else upstream_client(
            http_client=http_client, sleep=lambda _: None
        ).get_inventory("P100")


def test_inventory_client_distinguishes_idempotency_conflict_from_insufficient_inventory():
    http_client = SequencedHttpClient(
        [
            json_response(
                409,
                {"detail": "Idempotency-Key was already used for a different inventory adjustment"},
            )
        ]
    )

    with pytest.raises(InventoryIdempotencyConflictError):
        InventoryClient(http_client=http_client, sleep=lambda _: None).restore_inventory(
            "P100", 2, "order-cancel:order-123"
        )


def test_inventory_client_preserves_recognized_insufficient_inventory_conflict():
    http_client = SequencedHttpClient(
        [json_response(409, {"detail": "Insufficient inventory: 0 available, 2 requested"})]
    )

    with pytest.raises(InsufficientInventoryError, match="Insufficient inventory"):
        InventoryClient(http_client=http_client, sleep=lambda _: None).reduce_inventory(
            "P100", 2, "order-create:checkout-123"
        )


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(409, content=b"not-json"),
        json_response(409, {"detail": 123}),
        json_response(409, {"unexpected": "conflict"}),
    ],
)
def test_inventory_client_maps_malformed_conflict_payload_to_upstream_unavailable(response):
    http_client = SequencedHttpClient([response])

    with pytest.raises(UpstreamUnavailableError, match="conflict response validation failed"):
        InventoryClient(http_client=http_client, sleep=lambda _: None).reduce_inventory(
            "P100", 2, "order-create:checkout-123"
        )


@pytest.mark.parametrize("method_name", ["reduce_inventory", "restore_inventory"])
@pytest.mark.parametrize(
    ("payload", "expected_detail"),
    [
        ({"productId": "P100", "quantity": "not-a-quantity"}, "validation failed"),
        ({"productId": "P999", "quantity": 3}, "identifier mismatch"),
    ],
)
def test_inventory_patch_rejects_invalid_success_payload(method_name, payload, expected_detail):
    http_client = SequencedHttpClient([json_response(200, payload)])
    inventory_client = InventoryClient(http_client=http_client, sleep=lambda _: None)

    with pytest.raises(UpstreamUnavailableError, match=expected_detail):
        getattr(inventory_client, method_name)("P100", 2, "order-key")


def test_create_order_returns_201_and_confirmation():
    override_clients(
        FakeProductClient({"P100": {"id": "P100", "name": "Mouse", "price": 10.0}}),
        FakeInventoryClient({"P100": {"productId": "P100", "quantity": 5}}),
    )

    response = client.post("/orders", json=sample_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "CONFIRMED"
    assert body["totalPrice"] == 20.0


def test_create_order_reduces_inventory_by_requested_quantity():
    inventory_client = FakeInventoryClient({"P100": {"productId": "P100", "quantity": 5}})
    override_clients(
        FakeProductClient({"P100": {"id": "P100", "name": "Mouse", "price": 10.0}}),
        inventory_client,
    )

    client.post("/orders", json=sample_payload(quantity=2))

    assert inventory_client.reduced == ("P100", 2)


def test_create_order_forwards_idempotency_key_to_inventory_adjustment():
    inventory_client = FakeInventoryClient({"P100": {"productId": "P100", "quantity": 5}})
    override_clients(
        FakeProductClient({"P100": {"id": "P100", "price": 10.0}}),
        inventory_client,
    )

    response = client.post(
        "/orders",
        json=sample_payload(quantity=2),
        headers={"Idempotency-Key": "checkout-123"},
    )

    assert response.status_code == 201
    assert inventory_client.reduction_keys == ["order-create:checkout-123"]


def test_replayed_order_idempotency_key_returns_original_order_and_reduces_stock_once():
    inventory_client = FakeInventoryClient({"P100": {"productId": "P100", "quantity": 5}})
    override_clients(
        FakeProductClient({"P100": {"id": "P100", "price": 10.0}}),
        inventory_client,
    )
    headers = {"Idempotency-Key": "checkout-123"}

    first = client.post("/orders", json=sample_payload(quantity=2), headers=headers)
    replay = client.post("/orders", json=sample_payload(quantity=2), headers=headers)

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert len(order_repository.list()) == 1
    assert inventory_client.get_inventory("P100").quantity == 3
    assert inventory_client.reduction_keys == ["order-create:checkout-123"]


def test_replayed_order_idempotency_key_returns_creation_snapshot_after_cancellation():
    inventory_client = FakeInventoryClient({"P100": {"productId": "P100", "quantity": 5}})
    override_clients(
        FakeProductClient({"P100": {"id": "P100", "price": 10.0}}),
        inventory_client,
    )
    headers = {"Idempotency-Key": "checkout-123"}
    first = client.post("/orders", json=sample_payload(quantity=2), headers=headers)
    order_id = first.json()["id"]
    cancelled = client.patch(f"/orders/{order_id}", json={"status": "CANCELLED"})

    replay = client.post("/orders", json=sample_payload(quantity=2), headers=headers)

    assert cancelled.status_code == 200
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert replay.json()["status"] == "CONFIRMED"
    assert client.get(f"/orders/{order_id}").json()["status"] == "CANCELLED"


@pytest.mark.parametrize(
    "changed_payload",
    [
        sample_payload(customerId="C999"),
        sample_payload(productId="P999"),
        sample_payload(quantity=3),
        sample_payload(promotionCode="PROMO-10"),
    ],
)
def test_reusing_order_idempotency_key_with_different_payload_returns_409(changed_payload):
    inventory_client = FakeInventoryClient({"P100": {"productId": "P100", "quantity": 5}})
    override_clients(
        FakeProductClient({"P100": {"id": "P100", "price": 10.0}}),
        inventory_client,
    )
    headers = {"Idempotency-Key": "checkout-123"}
    first = client.post("/orders", json=sample_payload(), headers=headers)

    response = client.post("/orders", json=changed_payload, headers=headers)

    assert first.status_code == 201
    assert response.status_code == 409
    assert len(order_repository.list()) == 1
    assert inventory_client.get_inventory("P100").quantity == 3


def test_parallel_replay_returns_one_persisted_order_and_reduces_stock_once():
    inventory_client = FakeInventoryClient({"P100": {"productId": "P100", "quantity": 5}})
    override_clients(
        FakeProductClient({"P100": {"id": "P100", "price": 10.0}}),
        inventory_client,
    )
    start = Barrier(2)

    def create() -> tuple[int, dict]:
        start.wait()
        response = client.post(
            "/orders",
            json=sample_payload(),
            headers={"Idempotency-Key": "parallel-checkout"},
        )
        return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: create(), range(2)))

    assert [status_code for status_code, _ in results] == [201, 201]
    assert results[0][1] == results[1][1]
    assert len(order_repository.list()) == 1
    assert inventory_client.get_inventory("P100").quantity == 3
    assert inventory_client.reduction_keys == ["order-create:parallel-checkout"]


def test_same_idempotency_key_waits_for_pending_creation_and_replays_once() -> None:
    callback_started = Event()
    release_callback = Event()
    callback_calls: list[None] = []

    def create_once() -> Order:
        callback_calls.append(None)
        callback_started.set()
        assert release_callback.wait(timeout=2)
        return sample_order("order-one")

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            order_repository.create_idempotently,
            "same-key",
            "same-request",
            create_once,
        )
        assert callback_started.wait(timeout=1)
        second = executor.submit(
            order_repository.create_idempotently,
            "same-key",
            "same-request",
            create_once,
        )
        release_callback.set()
        results = [first.result(timeout=3), second.result(timeout=3)]

    assert [order.id for order in results] == ["order-one", "order-one"]
    assert callback_calls == [None]


def test_different_idempotency_keys_do_not_serialize_creation_callbacks() -> None:
    first_callback_started = Event()
    second_callback_started = Event()

    def create_first() -> Order:
        first_callback_started.set()
        assert second_callback_started.wait(timeout=2)
        return sample_order("order-one")

    def create_second() -> Order:
        second_callback_started.set()
        return sample_order("order-two")

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            order_repository.create_idempotently,
            "first-key",
            "first-request",
            create_first,
        )
        assert first_callback_started.wait(timeout=1)
        second = executor.submit(
            order_repository.create_idempotently,
            "second-key",
            "second-request",
            create_second,
        )
        results = [first.result(timeout=3), second.result(timeout=3)]

    assert [order.id for order in results] == ["order-one", "order-two"]


def test_failed_idempotent_creation_releases_claim_for_retry() -> None:
    def fail_creation() -> Order:
        raise RuntimeError("upstream failed")

    with pytest.raises(RuntimeError, match="upstream failed"):
        order_repository.create_idempotently("retry-key", "same-request", fail_creation)

    result = order_repository.create_idempotently(
        "retry-key",
        "same-request",
        lambda: sample_order("retry-order"),
    )

    assert result.id == "retry-order"


def test_expired_pending_idempotency_claim_can_be_recovered() -> None:
    with session_scope() as session:
        session.add(
            OrderIdempotencyClaimORM(
                idempotencyKey="expired-key",
                requestIdentity="same-request",
                ownerToken="abandoned-owner",
                leaseExpiresAt=datetime.now(UTC) - timedelta(seconds=1),
            )
        )

    result = order_repository.create_idempotently(
        "expired-key",
        "same-request",
        lambda: sample_order("recovered-order"),
    )

    assert result.id == "recovered-order"


def test_create_order_returns_404_when_product_missing():
    override_clients(
        FakeProductClient({}),
        FakeInventoryClient({"P100": {"productId": "P100", "quantity": 5}}),
    )

    response = client.post("/orders", json=sample_payload())
    assert response.status_code == 404


def test_create_order_returns_409_when_insufficient_stock():
    override_clients(
        FakeProductClient({"P100": {"id": "P100", "name": "Mouse", "price": 10.0}}),
        FakeInventoryClient({"P100": {"productId": "P100", "quantity": 1}}),
    )

    response = client.post("/orders", json=sample_payload(quantity=2))
    assert response.status_code == 409


def test_create_order_returns_502_when_upstream_unavailable():
    override_clients(
        FakeProductClient(error=UpstreamUnavailableError("product", "timed out")),
        FakeInventoryClient({"P100": {"productId": "P100", "quantity": 5}}),
    )

    response = client.post("/orders", json=sample_payload())
    assert response.status_code == 502


def test_create_order_returns_502_when_inventory_reduction_fails_after_validation():
    override_clients(
        FakeProductClient({"P100": {"id": "P100", "name": "Mouse", "price": 10.0}}),
        FakeInventoryClient(
            {"P100": {"productId": "P100", "quantity": 5}},
            reduce_error=UpstreamUnavailableError("inventory", "PATCH failed"),
        ),
    )

    response = client.post("/orders", json=sample_payload())
    assert response.status_code == 502
    assert order_repository.list() == []


def test_create_order_rejects_zero_quantity():
    response = client.post("/orders", json=sample_payload(quantity=0))
    assert response.status_code == 422


def test_list_orders_returns_created_orders():
    override_clients(
        FakeProductClient({"P100": {"id": "P100", "name": "Mouse", "price": 10.0}}),
        FakeInventoryClient({"P100": {"productId": "P100", "quantity": 5}}),
    )
    client.post("/orders", json=sample_payload())

    response = client.get("/orders")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_list_orders_paginates_in_creation_order(monkeypatch):
    order_ids = iter(
        [
            UUID("00000000-0000-0000-0000-000000000003"),
            UUID("00000000-0000-0000-0000-000000000001"),
            UUID("00000000-0000-0000-0000-000000000002"),
        ]
    )
    monkeypatch.setattr("app.routes.uuid.uuid4", lambda: next(order_ids))
    override_clients(
        FakeProductClient({"P100": {"id": "P100", "name": "Mouse", "price": 10.0}}),
        FakeInventoryClient({"P100": {"productId": "P100", "quantity": 10}}),
    )
    for customer_id in ("C300", "C100", "C200"):
        client.post("/orders", json=sample_payload(customerId=customer_id, quantity=1))

    response = client.get("/orders", params={"limit": 1, "offset": 1})

    assert response.status_code == 200
    assert [order["customerId"] for order in response.json()] == ["C100"]


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ],
)
def test_list_orders_rejects_invalid_pagination(params):
    response = client.get("/orders", params=params)
    assert response.status_code == 422


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong-key"}])
def test_order_routes_require_valid_api_key(headers):
    response = unauthenticated_client.get("/orders", headers=headers)
    assert response.status_code == 401


def test_get_order_returns_404_when_missing():
    response = client.get("/orders/does-not-exist")
    assert response.status_code == 404


def test_get_order_returns_existing_order():
    override_clients(
        FakeProductClient({"P100": {"id": "P100", "name": "Mouse", "price": 10.0}}),
        FakeInventoryClient({"P100": {"productId": "P100", "quantity": 5}}),
    )
    created = client.post("/orders", json=sample_payload()).json()

    response = client.get(f"/orders/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


def test_cancel_order_returns_200_and_restores_inventory():
    inventory_client = FakeInventoryClient({"P100": {"productId": "P100", "quantity": 3}})
    override_clients(
        FakeProductClient({"P100": {"id": "P100", "name": "Mouse", "price": 10.0}}),
        inventory_client,
    )
    created = client.post("/orders", json=sample_payload(quantity=2)).json()

    response = client.patch(f"/orders/{created['id']}", json={"status": "CANCELLED"})

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    assert inventory_client.restored == ("P100", 2)
    assert inventory_client.restore_keys == [f"order-cancel:{created['id']}"]


def test_creation_and_cancellation_inventory_keys_use_separate_namespaces(monkeypatch):
    order_id = UUID("00000000-0000-0000-0000-000000000123")
    monkeypatch.setattr("app.routes.uuid.uuid4", lambda: order_id)
    inventory_client = FakeInventoryClient({"P100": {"productId": "P100", "quantity": 5}})
    override_clients(
        FakeProductClient({"P100": {"id": "P100", "price": 10.0}}),
        inventory_client,
    )
    caller_key = f"order-cancel:{order_id}"

    created = client.post(
        "/orders",
        json=sample_payload(),
        headers={"Idempotency-Key": caller_key},
    )
    cancelled = client.patch(f"/orders/{order_id}", json={"status": "CANCELLED"})

    assert created.status_code == 201
    assert cancelled.status_code == 200
    assert inventory_client.reduction_keys == [f"order-create:{caller_key}"]
    assert inventory_client.restore_keys == [f"order-cancel:{order_id}"]


def test_cancel_order_returns_404_when_missing():
    response = client.patch("/orders/does-not-exist", json={"status": "CANCELLED"})
    assert response.status_code == 404


def test_cancel_order_returns_409_when_already_cancelled():
    override_clients(
        FakeProductClient({"P100": {"id": "P100", "name": "Mouse", "price": 10.0}}),
        FakeInventoryClient({"P100": {"productId": "P100", "quantity": 3}}),
    )
    created = client.post("/orders", json=sample_payload(quantity=2)).json()
    client.patch(f"/orders/{created['id']}", json={"status": "CANCELLED"})

    response = client.patch(f"/orders/{created['id']}", json={"status": "CANCELLED"})

    assert response.status_code == 409


def test_cancel_order_rejects_unsupported_status():
    override_clients(
        FakeProductClient({"P100": {"id": "P100", "name": "Mouse", "price": 10.0}}),
        FakeInventoryClient({"P100": {"productId": "P100", "quantity": 3}}),
    )
    created = client.post("/orders", json=sample_payload(quantity=2)).json()

    response = client.patch(f"/orders/{created['id']}", json={"status": "SHIPPED"})

    assert response.status_code == 422


def test_cancel_order_returns_502_when_inventory_restore_fails_and_order_stays_confirmed():
    override_clients(
        FakeProductClient({"P100": {"id": "P100", "name": "Mouse", "price": 10.0}}),
        FakeInventoryClient({"P100": {"productId": "P100", "quantity": 3}}),
    )
    created = client.post("/orders", json=sample_payload(quantity=2)).json()
    override_clients(
        FakeProductClient({"P100": {"id": "P100", "name": "Mouse", "price": 10.0}}),
        FakeInventoryClient(
            {"P100": {"productId": "P100", "quantity": 1}},
            reduce_error=UpstreamUnavailableError("inventory", "PATCH failed"),
        ),
    )

    response = client.patch(f"/orders/{created['id']}", json={"status": "CANCELLED"})

    assert response.status_code == 502
    assert order_repository.get(created["id"]).status == "CONFIRMED"


def test_cancel_order_returns_409_when_inventory_reports_idempotency_conflict():
    inventory_client = FakeInventoryClient({"P100": {"productId": "P100", "quantity": 3}})
    override_clients(
        FakeProductClient({"P100": {"id": "P100", "price": 10.0}}),
        inventory_client,
    )
    created = client.post("/orders", json=sample_payload(quantity=2)).json()
    conflict_client = InventoryClient(
        http_client=SequencedHttpClient(
            [
                json_response(
                    409,
                    {"detail": "Idempotency-Key was already used for a different inventory adjustment"},
                )
            ]
        ),
        sleep=lambda _: None,
    )
    override_clients(
        FakeProductClient({"P100": {"id": "P100", "price": 10.0}}),
        conflict_client,
    )

    response = TestClient(
        app,
        raise_server_exceptions=False,
        headers={"X-API-Key": "test-api-key"},
    ).patch(
        f"/orders/{created['id']}",
        json={"status": "CANCELLED"},
    )

    assert response.status_code == 409
    assert order_repository.get(created["id"]).status == "CONFIRMED"


def test_create_order_returns_409_when_inventory_rejects_the_reduction():
    # Stock drained between the availability check and the adjustment; the server-side delta rejects it.
    override_clients(
        FakeProductClient({"P100": {"id": "P100", "name": "Mouse", "price": 10.0}}),
        FakeInventoryClient(
            {"P100": {"productId": "P100", "quantity": 5}},
            reduce_error=InsufficientInventoryError("0 available, 2 requested"),
        ),
    )

    response = client.post("/orders", json=sample_payload(quantity=2))

    assert response.status_code == 409
    assert order_repository.list() == []


def test_health_returns_200():
    response = unauthenticated_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
