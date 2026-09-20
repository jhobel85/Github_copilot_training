"""Fixtures that boot the real Product, Inventory, and Order services for integration tests."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

REPO_ROOT = Path(__file__).resolve().parents[3]

PRODUCT_PORT = 18001
INVENTORY_PORT = 18002
ORDER_PORT = 18003

PRODUCT_URL = f"http://127.0.0.1:{PRODUCT_PORT}"
INVENTORY_URL = f"http://127.0.0.1:{INVENTORY_PORT}"
ORDER_URL = f"http://127.0.0.1:{ORDER_PORT}"

# app.config reads these at import time, so they must be set before any test module
# imports app.client / app.main.
os.environ["PRODUCT_SERVICE_URL"] = PRODUCT_URL
os.environ["INVENTORY_SERVICE_URL"] = INVENTORY_URL
os.environ["ORDER_SERVICE_URL"] = ORDER_URL
os.environ["API_KEY"] = "test-api-key"


def _wait_until_ready(base_url: str, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/health", timeout=1.0)
            if response.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(0.2)
    raise RuntimeError(f"Service at {base_url} did not become ready in time") from last_error


def _start_service(service_dir: str, port: int, extra_env: dict[str, str] | None = None) -> subprocess.Popen:
    cwd = REPO_ROOT / "services" / service_dir
    env = os.environ.copy()
    env.update(extra_env or {})
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=cwd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@pytest.fixture
def mcp_client_session() -> Callable[..., AbstractAsyncContextManager[ClientSession]]:
    @asynccontextmanager
    async def connect(*, product_url: str = PRODUCT_URL) -> AsyncIterator[ClientSession]:
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.main"],
            cwd=REPO_ROOT / "services" / "mcp_server",
            env={
                "API_KEY": os.environ["API_KEY"],
                "PRODUCT_SERVICE_URL": product_url,
                "INVENTORY_SERVICE_URL": INVENTORY_URL,
                "ORDER_SERVICE_URL": ORDER_URL,
            },
        )
        async with (
            stdio_client(server) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream, read_timeout_seconds=10) as session,
        ):
            await session.initialize()
            yield session

    return connect


@pytest.fixture(scope="session", autouse=True)
def running_services() -> Iterator[None]:
    """Boot Product, Inventory, and Order as real subprocesses for the whole test session."""
    # Each subprocess gets its own isolated in-memory database, so runs never leave a `*.db`
    # file behind or accumulate rows across separate test sessions.
    db_env = {
        "API_KEY": os.environ["API_KEY"],
        "DATABASE_URL": "sqlite:///:memory:",
    }
    processes = [
        _start_service("product_service", PRODUCT_PORT, extra_env=db_env),
        _start_service("inventory_service", INVENTORY_PORT, extra_env=db_env),
        _start_service(
            "order_service",
            ORDER_PORT,
            extra_env={
                "PRODUCT_SERVICE_URL": PRODUCT_URL,
                "INVENTORY_SERVICE_URL": INVENTORY_URL,
                **db_env,
            },
        ),
    ]
    try:
        for url in (PRODUCT_URL, INVENTORY_URL, ORDER_URL):
            _wait_until_ready(url)
        yield
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
