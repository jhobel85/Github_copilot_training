"""SQLAlchemy-backed repository for orders."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import Enum
from uuid import uuid4

from sqlalchemy import delete, text

from app.config import IDEMPOTENCY_TTL_SECONDS
from app.db import (
    Base,
    OrderIdempotencyClaimORM,
    OrderIdempotencyORM,
    OrderORM,
    engine,
    session_scope,
)
from app.models import Order

IDEMPOTENCY_LEASE_SECONDS = 60
IDEMPOTENCY_WAIT_SECONDS = 65
IDEMPOTENCY_POLL_SECONDS = 0.05


class OrderIdempotencyConflictError(Exception):
    """Raised when an order creation key is reused with a different payload."""


class OrderIdempotencyPendingError(Exception):
    """Raised when an in-progress idempotent creation does not complete in time."""


class _ClaimOutcome(Enum):
    ACQUIRED = "acquired"
    WAIT = "wait"


class OrderRepository:
    def list(self, limit: int = 50, offset: int = 0) -> list[Order]:
        with session_scope() as session:
            rows = (
                session.query(OrderORM)
                .order_by(OrderORM.createdAt.asc(), OrderORM.id.asc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return [Order.model_validate(row, from_attributes=True) for row in rows]

    def get(self, order_id: str) -> Order | None:
        with session_scope() as session:
            row = session.get(OrderORM, order_id)
            return Order.model_validate(row, from_attributes=True) if row else None

    def add(self, order: Order) -> Order:
        # Upsert: also used to persist a status transition (e.g. CONFIRMED -> CANCELLED) on an
        # already-created order, mirroring the original in-memory dict's overwrite-on-add semantics.
        with session_scope() as session:
            row = session.get(OrderORM, order.id)
            if row is None:
                row = OrderORM(**order.model_dump())
                session.add(row)
            else:
                for field, value in order.model_dump().items():
                    setattr(row, field, value)
            session.flush()
            session.refresh(row)
            return Order.model_validate(row, from_attributes=True)

    def create_idempotently(
        self,
        idempotency_key: str,
        request_identity: str,
        create_order: Callable[[], Order],
    ) -> Order:
        owner_token = str(uuid4())
        deadline = time.monotonic() + IDEMPOTENCY_WAIT_SECONDS
        self._prune_expired_idempotency()

        while True:
            outcome = self._claim_or_replay(idempotency_key, request_identity, owner_token)
            if isinstance(outcome, Order):
                return outcome
            if outcome is _ClaimOutcome.WAIT:
                if time.monotonic() >= deadline:
                    raise OrderIdempotencyPendingError("Timed out waiting for an in-progress order request")
                time.sleep(IDEMPOTENCY_POLL_SECONDS)
                continue

            try:
                order = create_order()
            except Exception:
                self._release_claim(idempotency_key, owner_token)
                raise

            persisted = self._finalize_claim(
                idempotency_key,
                request_identity,
                owner_token,
                order,
            )
            if persisted is not None:
                return persisted

    @staticmethod
    def _begin_write_transaction(session) -> None:
        if engine.dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))

    def _claim_or_replay(
        self,
        idempotency_key: str,
        request_identity: str,
        owner_token: str,
    ) -> _ClaimOutcome | Order:
        now = datetime.now(UTC)
        with session_scope() as session:
            self._begin_write_transaction(session)
            applied = session.get(OrderIdempotencyORM, idempotency_key)
            if applied is not None:
                self._validate_identity(applied.requestIdentity, request_identity)
                return Order.model_validate_json(applied.responseSnapshot)

            claim = session.get(OrderIdempotencyClaimORM, idempotency_key)
            if claim is None:
                session.add(
                    OrderIdempotencyClaimORM(
                        idempotencyKey=idempotency_key,
                        requestIdentity=request_identity,
                        ownerToken=owner_token,
                        leaseExpiresAt=now + timedelta(seconds=IDEMPOTENCY_LEASE_SECONDS),
                    )
                )
                session.flush()
                return _ClaimOutcome.ACQUIRED

            self._validate_identity(claim.requestIdentity, request_identity)
            lease_expires_at = claim.leaseExpiresAt
            if lease_expires_at.tzinfo is None:
                lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
            if lease_expires_at <= now:
                claim.ownerToken = owner_token
                claim.leaseExpiresAt = now + timedelta(seconds=IDEMPOTENCY_LEASE_SECONDS)
                session.flush()
                return _ClaimOutcome.ACQUIRED
            return _ClaimOutcome.WAIT

    def _release_claim(self, idempotency_key: str, owner_token: str) -> None:
        with session_scope() as session:
            self._begin_write_transaction(session)
            session.execute(
                delete(OrderIdempotencyClaimORM).where(
                    OrderIdempotencyClaimORM.idempotencyKey == idempotency_key,
                    OrderIdempotencyClaimORM.ownerToken == owner_token,
                )
            )

    def _finalize_claim(
        self,
        idempotency_key: str,
        request_identity: str,
        owner_token: str,
        order: Order,
    ) -> Order | None:
        with session_scope() as session:
            self._begin_write_transaction(session)
            deleted = session.execute(
                delete(OrderIdempotencyClaimORM).where(
                    OrderIdempotencyClaimORM.idempotencyKey == idempotency_key,
                    OrderIdempotencyClaimORM.ownerToken == owner_token,
                )
            )
            if deleted.rowcount == 0:
                return None

            row = OrderORM(**order.model_dump())
            session.add(row)
            session.flush()
            session.refresh(row)
            persisted_order = Order.model_validate(row, from_attributes=True)
            session.add(
                OrderIdempotencyORM(
                    idempotencyKey=idempotency_key,
                    requestIdentity=request_identity,
                    orderId=order.id,
                    responseSnapshot=persisted_order.model_dump_json(),
                    createdAt=datetime.now(UTC),
                )
            )
            session.flush()
            return persisted_order

    @staticmethod
    def _prune_expired_idempotency() -> None:
        """Drop settled idempotency records older than the TTL so persistent volumes
        stay bounded. In-flight claims live in a separate table and never qualify; a
        replay that arrives after its record was pruned simply behaves like a new request.
        """
        cutoff = datetime.now(UTC) - timedelta(seconds=IDEMPOTENCY_TTL_SECONDS)
        with session_scope() as session:
            session.execute(delete(OrderIdempotencyORM).where(OrderIdempotencyORM.createdAt < cutoff))

    @staticmethod
    def _validate_identity(stored_identity: str, request_identity: str) -> None:
        if stored_identity != request_identity:
            raise OrderIdempotencyConflictError(
                "Idempotency-Key was already used for a different order request"
            )

    def clear(self) -> None:
        """Used by tests to reset state between runs — drops and recreates the schema."""
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)


order_repository = OrderRepository()
