"""Engine configuration guarantees for the Product Service test deployment."""

from app.db import database_is_in_memory, database_url_supports_busy_timeout, engine
from sqlalchemy.pool import StaticPool


def test_in_memory_test_engine_uses_static_pool() -> None:
    assert isinstance(engine.pool, StaticPool)


def test_in_memory_test_engine_keeps_driver_default_busy_timeout() -> None:
    # In-memory + StaticPool never blocks, so no explicit busy timeout is set here:
    # the driver connection carries no configured timeout attribute at all.
    with engine.connect() as conn:
        assert not hasattr(conn.connection.dbapi_connection, "timeout")


def test_database_url_classifications_match_test_deployment() -> None:
    assert database_is_in_memory() is True
    assert database_url_supports_busy_timeout() is False


def test_file_backed_sqlite_url_gets_busy_timeout() -> None:
    assert database_url_supports_busy_timeout("sqlite:////data/product_service.db") is True
    assert database_url_supports_busy_timeout("sqlite:///./product_service.db") is True
    assert database_url_supports_busy_timeout("sqlite:///:memory:") is False
    assert database_url_supports_busy_timeout("postgresql+psycopg://u:p@db/orders") is False
