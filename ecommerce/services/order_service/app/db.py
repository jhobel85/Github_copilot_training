"""SQLAlchemy engine, session, and ORM models for the Order Service."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import DateTime, Engine, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./order_service.db")

_is_sqlite = DATABASE_URL.startswith("sqlite")
_is_in_memory = DATABASE_URL.endswith(":memory:")


def busy_timeout_for(url: str) -> float | None:
    """Busy timeout for a database URL, or `None` to keep the driver default.

    A longer busy timeout avoids `SQLITE_BUSY` when a file-backed writer and reader contend
    (e.g. the compose healthcheck reader vs. the app writer). In-memory + StaticPool never
    blocks, so the driver default is kept there to surface test logic errors fast.
    """
    if url.startswith("sqlite") and not url.endswith(":memory:"):
        return 30.0
    return None


def database_is_in_memory() -> bool:
    return DATABASE_URL.endswith(":memory:")


def database_url_supports_busy_timeout(url: str = DATABASE_URL) -> bool:
    return busy_timeout_for(url) is not None


_poolclass = StaticPool if _is_in_memory else None
_connect_args: dict[str, object] = {}
if _is_sqlite:
    _connect_args["check_same_thread"] = False
    _timeout = busy_timeout_for(DATABASE_URL)
    if _timeout is not None:
        _connect_args["timeout"] = _timeout

engine = create_engine(DATABASE_URL, connect_args=_connect_args, poolclass=_poolclass)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


class OrderORM(Base):
    """Column names mirror the `Order` Pydantic field names so `model_validate(row,
    from_attributes=True)` needs no extra mapping layer."""

    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    customerId: Mapped[str] = mapped_column(String, nullable=False)
    productId: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unitPrice: Mapped[float] = mapped_column(Float, nullable=False)
    totalPrice: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OrderIdempotencyORM(Base):
    """Persisted identity and result for an idempotent order creation."""

    __tablename__ = "order_idempotency"

    idempotencyKey: Mapped[str] = mapped_column(String, primary_key=True)
    requestIdentity: Mapped[str] = mapped_column(String, nullable=False)
    orderId: Mapped[str] = mapped_column(ForeignKey("orders.id"), unique=True, nullable=False)
    responseSnapshot: Mapped[str] = mapped_column(Text, nullable=False)
    # Settlement time so TTL pruning can drop old records; in-flight claims are a
    # separate table and never qualify for pruning.
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OrderIdempotencyClaimORM(Base):
    """Short-lived durable ownership claim for an in-progress order creation."""

    __tablename__ = "order_idempotency_claims"

    idempotencyKey: Mapped[str] = mapped_column(String, primary_key=True)
    requestIdentity: Mapped[str] = mapped_column(String, nullable=False)
    ownerToken: Mapped[str] = mapped_column(String, nullable=False)
    leaseExpiresAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# Added columns that pre-P12 persistent volumes lack. `create_all()` never alters
# existing tables, and SQLite rejects `ADD COLUMN` when the column already exists,
# so the addition is guarded with a pragma check. Table names come from this constant
# mapping, so the pragma string is free of user input.
_ADDED_COLUMNS: dict[str, tuple[str, str]] = {
    "order_idempotency": (
        "createdAt",
        "DATETIME NOT NULL DEFAULT (datetime('now'))",
    ),
}


def _sqlite_existing_columns(target: Engine) -> dict[str, set[str]]:
    """Map existing SQLite table name -> column names (empty when the table is absent)."""
    with target.connect() as conn:
        tables = {
            str(r[0]) for r in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")
        }
        result: dict[str, set[str]] = {}
        for table in tables:
            rows = conn.exec_driver_sql(f'PRAGMA table_info("{table}")').fetchall()
            result[table] = {str(r[1]) for r in rows}
    return result


def ensure_schema(target: Engine = engine) -> None:
    """Bootstrap fresh databases and apply one-shot additive migrations to old ones.

    Same migration shape as the Inventory Service: SQLite only allows constant defaults
    on `ADD COLUMN`, so the column is added nullable and backfilled with a SQL UPDATE.
    """
    Base.metadata.create_all(target)
    if target.dialect.name != "sqlite":
        return
    existing = _sqlite_existing_columns(target)
    for table, (column, _column_type) in _ADDED_COLUMNS.items():
        if table in existing and column not in existing[table]:
            with target.begin() as conn:
                conn.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN "{column}" DATETIME')
                conn.exec_driver_sql(
                    f'UPDATE "{table}" SET "{column}" = datetime(\'now\') WHERE "{column}" IS NULL'
                )


ensure_schema()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
