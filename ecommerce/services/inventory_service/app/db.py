"""SQLAlchemy engine, session, and ORM models for the Inventory Service."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./inventory_service.db")

_is_sqlite = DATABASE_URL.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _is_sqlite else {}
_poolclass = StaticPool if DATABASE_URL.endswith(":memory:") else None

engine = create_engine(DATABASE_URL, connect_args=_connect_args, poolclass=_poolclass)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


class InventoryORM(Base):
    """Column names mirror the `InventoryItem` Pydantic field names so `model_validate(row,
    from_attributes=True)` needs no extra mapping layer."""

    __tablename__ = "inventory"

    productId: Mapped[str] = mapped_column(String, primary_key=True)
    warehouse: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    lastUpdated: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AppliedInventoryAdjustmentORM(Base):
    """Persisted result of an idempotent quantity-delta request."""

    __tablename__ = "applied_inventory_adjustments"

    idempotencyKey: Mapped[str] = mapped_column(String, primary_key=True)
    productId: Mapped[str] = mapped_column(String, nullable=False)
    quantityDelta: Mapped[int] = mapped_column(Integer, nullable=False)
    resultWarehouse: Mapped[str] = mapped_column(String, nullable=False)
    resultQuantity: Mapped[int] = mapped_column(Integer, nullable=False)
    resultLastUpdated: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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
