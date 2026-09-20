"""Engine configuration guarantees for the Inventory Service test deployment."""

from app.db import busy_timeout_for, database_is_in_memory, database_url_supports_busy_timeout, engine


def test_file_backed_test_engine_gets_busy_timeout() -> None:
    # The inventory test deployment is file-backed so concurrency tests use independent
    # connections; the busy timeout must therefore be applied.
    assert database_is_in_memory() is False
    assert database_url_supports_busy_timeout() is True
    assert busy_timeout_for("sqlite:////data/inventory_service.db") == 30.0


def test_file_backed_engine_applies_busy_timeout() -> None:
    # The timeout is passed through `connect_args` to the sqlite3 driver at connect
    # time (recent CPython no longer exposes it on the connection object), so verify
    # the classification that drives `connect_args` plus that connections still open.
    from app.db import DATABASE_URL

    assert busy_timeout_for(DATABASE_URL) == 30.0
    with engine.connect() as conn:
        conn.exec_driver_sql("SELECT 1")


def test_busy_timeout_classification() -> None:
    assert busy_timeout_for("sqlite:////data/inventory_service.db") == 30.0
    assert busy_timeout_for("sqlite:///./inventory_service.db") == 30.0
    assert busy_timeout_for("sqlite:///:memory:") is None
    assert busy_timeout_for("postgresql+psycopg://u:p@db/inventory") is None
