"""TTL pruning for persisted idempotency records (hardening plan, Phase 12)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.config import IDEMPOTENCY_TTL_SECONDS
from app.db import AppliedInventoryAdjustmentORM, _sqlite_existing_columns, engine, ensure_schema
from app.main import app
from app.storage import inventory_repository
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

client = TestClient(app, headers={"X-API-Key": "test-api-key"})


@pytest.fixture(autouse=True)
def reset_repository() -> None:
    inventory_repository.clear()
    yield
    inventory_repository.clear()


def _backdate_record(key: str, age_seconds: float) -> None:
    cutoff = datetime.now(UTC) - timedelta(seconds=age_seconds)
    with Session(engine) as session:
        row = session.get(AppliedInventoryAdjustmentORM, key)
        assert row is not None
        row.appliedAt = cutoff
        session.commit()


def _record_keys() -> set[str]:
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(select(AppliedInventoryAdjustmentORM.idempotencyKey))}


def test_backdated_record_is_pruned_and_key_is_treated_as_new():
    client.post("/inventory", json={"productId": "P100", "warehouse": "WH-1", "quantity": 10})

    first = client.patch("/inventory/P100", json={"quantityDelta": -2}, headers={"Idempotency-Key": "key-A"})
    assert first.status_code == 200
    assert first.json()["quantity"] == 8

    # Backdate beyond the TTL, then run any key-bearing delta to trigger pruning.
    _backdate_record("key-A", IDEMPOTENCY_TTL_SECONDS + 3600)
    second = client.patch("/inventory/P100", json={"quantityDelta": -1}, headers={"Idempotency-Key": "key-B"})
    assert second.status_code == 200
    assert second.json()["quantity"] == 7
    assert _record_keys() == {"key-B"}  # key-A pruned, key-B kept

    # key-A is gone, so reusing it is a fresh adjustment rather than a replay.
    third = client.patch("/inventory/P100", json={"quantityDelta": -2}, headers={"Idempotency-Key": "key-A"})
    assert third.status_code == 200
    assert third.json()["quantity"] == 5
    assert _record_keys() == {"key-A", "key-B"}


def test_within_ttl_replay_returns_stored_snapshot():
    client.post("/inventory", json={"productId": "P100", "warehouse": "WH-1", "quantity": 10})

    first = client.patch("/inventory/P100", json={"quantityDelta": -2}, headers={"Idempotency-Key": "key-A"})
    assert first.status_code == 200
    snapshot = first.json()

    replay = client.patch("/inventory/P100", json={"quantityDelta": -2}, headers={"Idempotency-Key": "key-A"})
    assert replay.status_code == 200
    assert replay.json() == snapshot
    assert _record_keys() == {"key-A"}


def test_fresh_record_survives_pruning_of_expired_neighbor():
    client.post("/inventory", json={"productId": "P100", "warehouse": "WH-1", "quantity": 10})
    client.patch("/inventory/P100", json={"quantityDelta": -1}, headers={"Idempotency-Key": "keep-me"})

    # A record backdated past the TTL is pruned by the next delta that keeps fresh ones.
    _backdate_record("keep-me", IDEMPOTENCY_TTL_SECONDS + 3600)
    client.patch("/inventory/P100", json={"quantityDelta": -1}, headers={"Idempotency-Key": "other-key"})
    assert _record_keys() == {"other-key"}


def _create_old_style_inventory_table(target: Engine) -> None:
    """Build the pre-P12 schema (no `appliedAt`) into a scratch database."""
    ddl = [
        """CREATE TABLE inventory (
            productId VARCHAR NOT NULL PRIMARY KEY,
            warehouse VARCHAR NOT NULL,
            quantity INTEGER NOT NULL,
            lastUpdated DATETIME NOT NULL
        )""",
        """CREATE TABLE applied_inventory_adjustments (
            idempotencyKey VARCHAR NOT NULL PRIMARY KEY,
            productId VARCHAR NOT NULL,
            quantityDelta INTEGER NOT NULL,
            resultWarehouse VARCHAR NOT NULL,
            resultQuantity INTEGER NOT NULL,
            resultLastUpdated DATETIME NOT NULL
        )""",
    ]
    with target.begin() as conn:
        for statement in ddl:
            conn.exec_driver_sql(statement)
        conn.exec_driver_sql(
            "INSERT INTO applied_inventory_adjustments (idempotencyKey, productId, quantityDelta, "
            "resultWarehouse, resultQuantity, resultLastUpdated) VALUES "
            "(?, ?, ?, ?, ?, ?)",
            ("legacy-key", "P100", -2, "WH-1", 8, "2026-01-01T00:00:00+00:00"),
        )


def test_existing_volume_upgrade_adds_missing_column(tmp_path):
    db_path = tmp_path / "legacy.db"
    scratch: Engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    _create_old_style_inventory_table(scratch)

    ensure_schema(scratch)

    assert "appliedAt" in _sqlite_existing_columns(scratch)["applied_inventory_adjustments"]

    # The default backfills the pre-existing row so the ORM can read it.
    with Session(scratch) as session:
        row = session.get(AppliedInventoryAdjustmentORM, "legacy-key")
    assert row is not None
    assert row.appliedAt is not None
    assert row.quantityDelta == -2

    scratch.dispose()
