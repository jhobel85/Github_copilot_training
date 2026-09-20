import pytest
from app.main import app
from app.storage import product_repository
from fastapi.testclient import TestClient

client = TestClient(app, headers={"X-API-Key": "test-api-key"})
unauthenticated_client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_repository():
    product_repository.clear()
    yield
    product_repository.clear()


def sample_payload(**overrides):
    payload = {
        "name": "Wireless Mouse",
        "category": "Electronics",
        "price": 29.99,
        "description": "Ergonomic wireless mouse",
    }
    payload.update(overrides)
    return payload


def test_create_product_returns_201_and_id():
    response = client.post("/products", json=sample_payload())
    assert response.status_code == 201
    body = response.json()
    assert body["id"]
    assert body["name"] == "Wireless Mouse"


def test_list_products_returns_created_products():
    client.post("/products", json=sample_payload())
    response = client.get("/products")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_list_products_paginates_in_stable_order():
    for name in ("Mouse", "Keyboard", "Monitor"):
        client.post("/products", json=sample_payload(name=name))

    all_products = client.get("/products", params={"limit": 100, "offset": 0}).json()
    response = client.get("/products", params={"limit": 1, "offset": 1})

    assert response.status_code == 200
    assert response.json() == all_products[1:2]


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ],
)
def test_list_products_rejects_invalid_pagination(params):
    response = client.get("/products", params=params)
    assert response.status_code == 422


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong-key"}])
def test_product_routes_require_valid_api_key(headers):
    response = unauthenticated_client.get("/products", headers=headers)
    assert response.status_code == 401


def test_get_product_returns_404_when_missing():
    response = client.get("/products/does-not-exist")
    assert response.status_code == 404


def test_get_product_returns_existing_product():
    created = client.post("/products", json=sample_payload()).json()
    response = client.get(f"/products/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


def test_update_product_returns_updated_data():
    created = client.post("/products", json=sample_payload()).json()
    response = client.put(f"/products/{created['id']}", json=sample_payload(price=19.99))
    assert response.status_code == 200
    assert response.json()["price"] == 19.99


def test_update_product_returns_404_when_missing():
    response = client.put("/products/does-not-exist", json=sample_payload())
    assert response.status_code == 404


def test_delete_product_returns_204():
    created = client.post("/products", json=sample_payload()).json()
    response = client.delete(f"/products/{created['id']}")
    assert response.status_code == 204


def test_delete_product_returns_404_when_missing():
    response = client.delete("/products/does-not-exist")
    assert response.status_code == 404


def test_create_product_rejects_invalid_price():
    response = client.post("/products", json=sample_payload(price=-5))
    assert response.status_code == 422


def test_create_product_rejects_whitespace_only_name():
    response = client.post("/products", json=sample_payload(name="   "))
    assert response.status_code == 422


def test_health_returns_200():
    response = unauthenticated_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
