"""TTL pruning for persisted order idempotency records (hardening plan, Phase 12)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.config import IDEMPOTENCY_TTL_SECONDS
from app.db import OrderIdempotencyORM, _sqlite_existing_columns, engine, ensure_schema
from app.main import app
from app.models import Order
from app.storage import OrderIdempotencyConflictError, order_repository
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


@pytest.fixture(autouse=True)
def reset_repository():
    order_repository.clear()
    yield
    order_repository.clear()
    app.dependency_overrides.clear()


def _order_identity(customer_id: str = "cust-1", product_id: str = "P100", quantity: int = 2) -> str:
    import json

    return json.dumps(
        {"customerId": customer_id, "productId": product_id, "quantity": quantity}, sort_keys=True
    )


def _backdate_record(key: str, age_seconds: float) -> None:
    cutoff = datetime.now(UTC) - timedelta(seconds=age_seconds)
    with Session(engine) as session:
        row = session.get(OrderIdempotencyORM, key)
        assert row is not None
        row.createdAt = cutoff
        session.commit()


def _record_keys() -> set[str]:
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(select(OrderIdempotencyORM.idempotencyKey))}


class _OrderFactory:
    def __init__(self, order: Order) -> None:
        self._order = order

    def __call__(self) -> Order:
        return self._order


def _order(customer: str = "cust-1") -> Order:
    import uuid

    return Order(
        id=str(uuid.uuid4()),
        customerId=customer,
        productId="P100",
        quantity=2,
        unitPrice=10.0,
        totalPrice=20.0,
        status="CONFIRMED",
        createdAt=datetime.now(UTC),
    )


def test_backdated_record_is_pruned_and_key_is_reclaimable():
    identity = _order_identity()
    first = order_repository.create_idempotently("key-A", identity, _OrderFactory(_order()))
    assert _record_keys() == {"key-A"}

    _backdate_record("key-A", IDEMPOTENCY_TTL_SECONDS + 3600)
    second = order_repository.create_idempotently("key-A", identity, _OrderFactory(_order()))

    # key-A was pruned, so a new record exists under it with a *different* order id.
    assert _record_keys() == {"key-A"}
    assert second.id != first.id


def test_within_ttl_replay_returns_stored_order():
    identity = _order_identity()
    factory = _OrderFactory(_order())
    first = order_repository.create_idempotently("key-A", identity, factory)
    replay = order_repository.create_idempotently("key-A", identity, _OrderFactory(_order()))
    assert replay.id == first.id
    assert _record_keys() == {"key-A"}


def test_conflicting_identity_still_conflicts_after_prune_window():
    identity_a = _order_identity(customer_id="cust-A")
    identity_b = _order_identity(customer_id="cust-B")
    order_repository.create_idempotently("key-A", identity_a, _OrderFactory(_order("cust-A")))

    with pytest.raises(OrderIdempotencyConflictError):
        order_repository.create_idempotently("key-A", identity_b, _OrderFactory(_order("cust-B")))


def test_pruning_happens_without_any_new_creation():
    identity = _order_identity()
    order_repository.create_idempotently("key-A", identity, _OrderFactory(_order()))
    _backdate_record("key-A", IDEMPOTENCY_TTL_SECONDS + 3600)

    # Any subsequent key-bearing creation triggers the prune.
    order_repository.create_idempotently(
        "key-B", _order_identity(customer_id="cust-2"), _OrderFactory(_order("cust-2"))
    )
    assert _record_keys() == {"key-B"}


def test_existing_volume_upgrade_adds_missing_column(tmp_path):
    db_path = tmp_path / "legacy.db"
    scratch: Engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    _create_old_style_order_tables(scratch)

    ensure_schema(scratch)

    assert "createdAt" in _sqlite_existing_columns(scratch)["order_idempotency"]

    # The column is backfilled so the ORM can read pre-existing rows.
    with Session(scratch) as session:
        row = session.get(OrderIdempotencyORM, "legacy-key")
    assert row is not None
    assert row.createdAt is not None
    scratch.dispose()


def _create_old_style_order_tables(target: Engine) -> None:
    """Build the pre-P12 order schema (no `order_idempotency.createdAt`)."""
    ddl = [
        """CREATE TABLE orders (
            id VARCHAR NOT NULL PRIMARY KEY,
            customerId VARCHAR NOT NULL,
            productId VARCHAR NOT NULL,
            quantity INTEGER NOT NULL,
            unitPrice FLOAT NOT NULL,
            totalPrice FLOAT NOT NULL,
            status VARCHAR NOT NULL,
            createdAt DATETIME NOT NULL
        )""",
        """CREATE TABLE order_idempotency (
            idempotencyKey VARCHAR NOT NULL PRIMARY KEY,
            requestIdentity VARCHAR NOT NULL,
            orderId VARCHAR NOT NULL UNIQUE,
            responseSnapshot VARCHAR NOT NULL
        )""",
        """CREATE TABLE order_idempotency_claims (
            idempotencyKey VARCHAR NOT NULL PRIMARY KEY,
            requestIdentity VARCHAR NOT NULL,
            ownerToken VARCHAR NOT NULL,
            leaseExpiresAt DATETIME NOT NULL
        )""",
    ]
    with target.begin() as conn:
        for statement in ddl:
            conn.exec_driver_sql(statement)
        conn.exec_driver_sql(
            "INSERT INTO orders (id, customerId, productId, quantity, unitPrice, totalPrice, status, createdAt) "
            "VALUES (?, 'cust-1', 'P100', 2, 10.0, 20.0, 'CONFIRMED', '2026-01-01T00:00:00+00:00')",
            ("legacy-order",),
        )
        conn.exec_driver_sql(
            "INSERT INTO order_idempotency (idempotencyKey, requestIdentity, orderId, responseSnapshot) "
            "VALUES ('legacy-key', '{}', 'legacy-order', '{}')"
        )
