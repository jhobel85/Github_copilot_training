from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from app.db import InventoryORM
from app.main import app
from app.storage import inventory_repository
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

client = TestClient(app, headers={"X-API-Key": "test-api-key"})
unauthenticated_client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_repository():
    inventory_repository.clear()
    yield
    inventory_repository.clear()


def sample_payload(**overrides):
    payload = {
        "productId": "P100",
        "warehouse": "WH-EAST",
        "quantity": 50,
    }
    payload.update(overrides)
    return payload


def test_create_inventory_returns_201():
    response = client.post("/inventory", json=sample_payload())
    assert response.status_code == 201
    body = response.json()
    assert body["productId"] == "P100"
    assert body["quantity"] == 50
    assert body["lastUpdated"]


def test_create_inventory_returns_409_when_product_already_tracked():
    client.post("/inventory", json=sample_payload())
    response = client.post("/inventory", json=sample_payload())
    assert response.status_code == 409


def test_concurrent_create_inventory_returns_one_created_and_one_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookup_complete = Barrier(2)
    original_get = Session.get

    def synchronized_get(self, entity, ident, **kwargs):
        result = original_get(self, entity, ident, **kwargs)
        if entity is InventoryORM and ident == "P100":
            lookup_complete.wait()
        return result

    monkeypatch.setattr(Session, "get", synchronized_get)
    concurrent_client = TestClient(
        app,
        headers={"X-API-Key": "test-api-key"},
        raise_server_exceptions=False,
    )
    start = Barrier(2)

    def create() -> int:
        start.wait()
        return concurrent_client.post("/inventory", json=sample_payload()).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        status_codes = list(executor.map(lambda _: create(), range(2)))

    assert sorted(status_codes) == [201, 409]
    assert [item.productId for item in inventory_repository.list()] == ["P100"]


def test_list_inventory_returns_created_items():
    client.post("/inventory", json=sample_payload())
    response = client.get("/inventory")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_list_inventory_paginates_in_product_id_order():
    for product_id in ("P300", "P100", "P200"):
        client.post("/inventory", json=sample_payload(productId=product_id))

    response = client.get("/inventory", params={"limit": 1, "offset": 1})

    assert response.status_code == 200
    assert [item["productId"] for item in response.json()] == ["P200"]


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ],
)
def test_list_inventory_rejects_invalid_pagination(params):
    response = client.get("/inventory", params=params)
    assert response.status_code == 422


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong-key"}])
def test_inventory_routes_require_valid_api_key(headers):
    response = unauthenticated_client.get("/inventory", headers=headers)
    assert response.status_code == 401


def test_get_inventory_returns_404_when_missing():
    response = client.get("/inventory/does-not-exist")
    assert response.status_code == 404


def test_get_inventory_returns_existing_item():
    created = client.post("/inventory", json=sample_payload()).json()
    response = client.get(f"/inventory/{created['productId']}")
    assert response.status_code == 200
    assert response.json() == created


def test_update_inventory_returns_updated_quantity():
    client.post("/inventory", json=sample_payload())
    response = client.patch("/inventory/P100", json={"quantity": 10})
    assert response.status_code == 200
    assert response.json()["quantity"] == 10
    assert response.json()["warehouse"] == "WH-EAST"


def test_update_inventory_returns_404_when_missing():
    response = client.patch("/inventory/does-not-exist", json={"quantity": 10})
    assert response.status_code == 404


def test_create_inventory_rejects_negative_quantity():
    response = client.post("/inventory", json=sample_payload(quantity=-1))
    assert response.status_code == 422


def test_create_inventory_rejects_missing_required_field():
    payload = sample_payload()
    del payload["quantity"]
    response = client.post("/inventory", json=payload)
    assert response.status_code == 422


def test_update_inventory_rejects_negative_quantity():
    client.post("/inventory", json=sample_payload())
    response = client.patch("/inventory/P100", json={"quantity": -5})
    assert response.status_code == 422


def test_update_inventory_ignores_explicit_null_field():
    client.post("/inventory", json=sample_payload())
    response = client.patch("/inventory/P100", json={"warehouse": None})
    assert response.status_code == 200
    assert response.json()["warehouse"] == "WH-EAST"


def test_update_inventory_applies_negative_delta_against_stored_quantity():
    client.post("/inventory", json=sample_payload(quantity=50))
    response = client.patch("/inventory/P100", json={"quantityDelta": -20})
    assert response.status_code == 200
    assert response.json()["quantity"] == 30


def test_update_inventory_applies_positive_delta_against_stored_quantity():
    client.post("/inventory", json=sample_payload(quantity=50))
    response = client.patch("/inventory/P100", json={"quantityDelta": 5})
    assert response.status_code == 200
    assert response.json()["quantity"] == 55


def test_update_inventory_replays_persisted_result_for_same_idempotency_key():
    client.post("/inventory", json=sample_payload(quantity=50))
    headers = {"Idempotency-Key": "order-123-reserve"}

    first = client.patch("/inventory/P100", json={"quantityDelta": -5}, headers=headers)
    replay = client.patch("/inventory/P100", json={"quantityDelta": -5}, headers=headers)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert client.get("/inventory/P100").json()["quantity"] == 45


def test_update_inventory_rejects_reusing_key_for_different_adjustment():
    client.post("/inventory", json=sample_payload(quantity=50))
    headers = {"Idempotency-Key": "order-123-reserve"}
    client.patch("/inventory/P100", json={"quantityDelta": -5}, headers=headers)

    response = client.patch("/inventory/P100", json={"quantityDelta": -7}, headers=headers)

    assert response.status_code == 409
    assert client.get("/inventory/P100").json()["quantity"] == 45


def test_update_inventory_rejects_reusing_key_for_nonexistent_different_product():
    client.post("/inventory", json=sample_payload(quantity=50))
    headers = {"Idempotency-Key": "order-123-reserve"}
    client.patch("/inventory/P100", json={"quantityDelta": -5}, headers=headers)

    response = client.patch("/inventory/does-not-exist", json={"quantityDelta": -5}, headers=headers)

    assert response.status_code == 409
    assert client.get("/inventory/P100").json()["quantity"] == 45


def test_parallel_quantity_deltas_never_lose_successful_updates() -> None:
    initial_quantity = 50
    deltas = (2, -1) * 16
    client.post("/inventory", json=sample_payload(quantity=initial_quantity))
    start = Barrier(len(deltas))

    def patch_delta(delta: int) -> tuple[int, int]:
        start.wait()
        response = client.patch("/inventory/P100", json={"quantityDelta": delta})
        return delta, response.status_code

    with ThreadPoolExecutor(max_workers=len(deltas)) as executor:
        results = list(executor.map(patch_delta, deltas))

    successful_deltas = [delta for delta, status_code in results if status_code == 200]
    assert len(successful_deltas) == len(deltas)

    response = client.get("/inventory/P100")
    assert response.status_code == 200
    assert response.json()["quantity"] == initial_quantity + sum(successful_deltas)


def test_update_inventory_returns_409_when_delta_would_go_negative():
    client.post("/inventory", json=sample_payload(quantity=3))
    response = client.patch("/inventory/P100", json={"quantityDelta": -5})
    assert response.status_code == 409
    assert response.json()["detail"]


def test_update_inventory_rejects_both_quantity_and_delta():
    client.post("/inventory", json=sample_payload())
    response = client.patch("/inventory/P100", json={"quantity": 10, "quantityDelta": -1})
    assert response.status_code == 422


def test_health_returns_200():
    response = unauthenticated_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
