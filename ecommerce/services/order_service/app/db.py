"""SQLAlchemy engine, session, and ORM models for the Order Service."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./order_service.db")

_is_sqlite = DATABASE_URL.startswith("sqlite")
_connect_args = {"check_same_thread": False, "timeout": 30} if _is_sqlite else {}
_poolclass = StaticPool if DATABASE_URL.endswith(":memory:") else None

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


class OrderIdempotencyClaimORM(Base):
    """Short-lived durable ownership claim for an in-progress order creation."""

    __tablename__ = "order_idempotency_claims"

    idempotencyKey: Mapped[str] = mapped_column(String, primary_key=True)
    requestIdentity: Mapped[str] = mapped_column(String, nullable=False)
    ownerToken: Mapped[str] = mapped_column(String, nullable=False)
    leaseExpiresAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


Base.metadata.create_all(engine)


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
