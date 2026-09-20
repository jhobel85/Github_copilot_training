"""Test-only configuration: force an isolated in-memory SQLite database.

Must set this before any test module imports `app.main` / `app.db`, since the engine is
created at import time.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["API_KEY"] = "test-api-key"
