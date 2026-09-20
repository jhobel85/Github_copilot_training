"""Test-only configuration: force an isolated temporary SQLite database.

Must set this before any test module imports `app.main` / `app.db`, since the engine is
created at import time. A file-backed database gives concurrent requests separate
connections, unlike SQLite's single-connection in-memory test setup.
"""

import os
from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4

import pytest

_TEST_DATABASE_PATH = Path(gettempdir()) / f"inventory-tests-{uuid4().hex}.db"
_TEST_DATABASE_URL = f"sqlite:///{_TEST_DATABASE_PATH.as_posix()}"
os.environ["DATABASE_URL"] = _TEST_DATABASE_URL
os.environ["API_KEY"] = "test-api-key"


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    from app.db import engine

    engine.dispose()
    _TEST_DATABASE_PATH.unlink(missing_ok=True)
