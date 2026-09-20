"""SQLAlchemy engine, session, and ORM models for the Product Service."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Float, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./product_service.db")

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


class ProductORM(Base):
    """Column names mirror the `Product` Pydantic field names so `model_validate(row,
    from_attributes=True)` needs no extra mapping layer."""

    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)


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
