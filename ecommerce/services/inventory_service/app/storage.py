"""SQLAlchemy-backed repository for inventory items."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError

from app.db import AppliedInventoryAdjustmentORM, Base, InventoryORM, engine, session_scope
from app.models import InventoryCreate, InventoryItem, InventoryUpdate


class InsufficientInventoryError(Exception):
    """Raised when a quantityDelta would drive stock below zero."""

    def __init__(self, product_id: str, available: int, requested: int) -> None:
        self.product_id = product_id
        self.available = available
        self.requested = requested
        super().__init__(
            f"Insufficient inventory for product '{product_id}': {available} available, {requested} requested"
        )


class IdempotencyKeyConflictError(Exception):
    """Raised when an idempotency key is reused for a different adjustment."""


class InventoryRepository:
    def list(self, limit: int = 50, offset: int = 0) -> list[InventoryItem]:
        with session_scope() as session:
            rows = (
                session.query(InventoryORM)
                .order_by(InventoryORM.productId.asc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return [InventoryItem.model_validate(row, from_attributes=True) for row in rows]

    def get(self, product_id: str) -> InventoryItem | None:
        with session_scope() as session:
            row = session.get(InventoryORM, product_id)
            return InventoryItem.model_validate(row, from_attributes=True) if row else None

    def create(self, data: InventoryCreate) -> InventoryItem | None:
        try:
            with session_scope() as session:
                row = InventoryORM(
                    productId=data.productId,
                    warehouse=data.warehouse,
                    quantity=data.quantity,
                    lastUpdated=datetime.now(UTC),
                )
                session.add(row)
                session.flush()
                session.refresh(row)
                return InventoryItem.model_validate(row, from_attributes=True)
        except IntegrityError:
            return None

    def update(
        self,
        product_id: str,
        data: InventoryUpdate,
        idempotency_key: str | None = None,
    ) -> InventoryItem | None:
        # Explicit nulls are treated as "no change" so PATCH can never null out a required field.
        updates = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
        delta = updates.pop("quantityDelta", None)

        try:
            with session_scope() as session:
                if delta is not None and idempotency_key is not None:
                    applied = session.get(AppliedInventoryAdjustmentORM, idempotency_key)
                    if applied is not None:
                        return self._replay(applied, product_id, delta)

                row = session.get(InventoryORM, product_id)
                if row is None:
                    return None

                if delta is not None:
                    # Resolved and applied atomically in the WHERE-guarded UPDATE itself, so two
                    # concurrent adjustments race in SQL, not in a Python read-then-write.
                    result = session.execute(
                        sa_update(InventoryORM)
                        .where(InventoryORM.productId == product_id, InventoryORM.quantity + delta >= 0)
                        .values(quantity=InventoryORM.quantity + delta, lastUpdated=datetime.now(UTC))
                    )
                    if result.rowcount == 0:
                        raise InsufficientInventoryError(product_id, row.quantity, -delta)
                    session.refresh(row)
                    item = InventoryItem.model_validate(row, from_attributes=True)
                    if idempotency_key is not None:
                        session.add(
                            AppliedInventoryAdjustmentORM(
                                idempotencyKey=idempotency_key,
                                productId=product_id,
                                quantityDelta=delta,
                                resultWarehouse=item.warehouse,
                                resultQuantity=item.quantity,
                                resultLastUpdated=item.lastUpdated,
                            )
                        )
                        session.flush()
                    return item

                for field, value in updates.items():
                    setattr(row, field, value)
                row.lastUpdated = datetime.now(UTC)
                session.flush()
                session.refresh(row)
                return InventoryItem.model_validate(row, from_attributes=True)
        except IntegrityError:
            # Concurrent requests can both miss the initial lookup. The losing transaction
            # rolls back its delta with the failed insert, then replays the committed result.
            if idempotency_key is None or delta is None:
                raise
            with session_scope() as session:
                applied = session.get(AppliedInventoryAdjustmentORM, idempotency_key)
                if applied is None:
                    raise
                return self._replay(applied, product_id, delta)

    @staticmethod
    def _replay(
        applied: AppliedInventoryAdjustmentORM,
        product_id: str,
        delta: int,
    ) -> InventoryItem:
        if applied.productId != product_id or applied.quantityDelta != delta:
            raise IdempotencyKeyConflictError(
                "Idempotency-Key was already used for a different inventory adjustment"
            )
        return InventoryItem(
            productId=applied.productId,
            warehouse=applied.resultWarehouse,
            quantity=applied.resultQuantity,
            lastUpdated=applied.resultLastUpdated,
        )

    def clear(self) -> None:
        """Used by tests to reset state between runs — drops and recreates the schema."""
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)


inventory_repository = InventoryRepository()
