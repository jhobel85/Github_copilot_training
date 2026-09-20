"""Boot the three API services as real uvicorn subprocesses for browser tests.

The walkthrough drives the services' Swagger UI (``/docs``) in a real Chromium
browser, so the services must be listening on real ports — ``TestClient`` alone
is not sufficient. Each service gets:

* a unique test API key (``API_KEY``),
* an isolated temporary SQLite file (``DATABASE_URL``),
* for the Order Service, the Product/Inventory URLs of this test instance,
* non-default ports (8101-8103) so a locally composed/started stack does not
  collide.

All state is torn down at the end of the pytest session.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from .tunnels import start_tunnels, stop_all

REPO_ROOT = Path(__file__).resolve().parents[2]
API_KEY = "browser-test-api-key"
PRODUCT_PORT = 8101
INVENTORY_PORT = 8102
ORDER_PORT = 8103
PRODUCT_URL = f"http://localhost:{PRODUCT_PORT}"
INVENTORY_URL = f"http://localhost:{INVENTORY_PORT}"
ORDER_URL = f"http://localhost:{ORDER_PORT}"


def _service_dir(name: str) -> Path:
    return REPO_ROOT / "services" / name


def _verify_public_urls(public: dict[str, str], timeout: float = 45.0) -> bool:
    """Poll the public health endpoints; True if any answers 200 within ``timeout``.

    On networks whose egress proxy blocks Cloudflare's edge ports (7844) the
    minted URL stays at 530 — this distinguishes that from normal propagation
    delay (seconds) and lets the banner advise the user.
    """
    if not public:
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for url in public.values():
            try:
                with urllib.request.urlopen(f"{url}/health", timeout=5) as resp:
                    if resp.status == 200:
                        return True
            except OSError:
                pass
        time.sleep(3)
    return False


def _wait_healthy(url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=2) as resp:
                if resp.status == 200:
                    return
        except OSError as exc:  # connection refused while the service is starting
            last = exc
        time.sleep(0.5)
    raise RuntimeError(f"{url} did not become healthy: {last}")


def _start_service(name: str, port: int, extra_env: dict[str, str], tmp_dir: Path) -> subprocess.Popen[bytes]:
    env = dict(os.environ)
    env.update(
        {
            "API_KEY": API_KEY,
            "DATABASE_URL": f"sqlite:///{(tmp_dir / f'{name}.db')}",
            **extra_env,
        }
    )
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=_service_dir(name),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@pytest.fixture(scope="session")
def services() -> Iterator[dict[str, str]]:
    """Run the full three-service stack for the session; urls + key for the UI."""
    tmp_dir = Path(tempfile.gettempdir()) / f"browser-tests-{uuid4().hex}"
    tmp_dir.mkdir(parents=True)
    procs: list[subprocess.Popen[bytes]] = [
        _start_service("product_service", PRODUCT_PORT, {}, tmp_dir),
        _start_service("inventory_service", INVENTORY_PORT, {}, tmp_dir),
        _start_service(
            "order_service",
            ORDER_PORT,
            {
                "PRODUCT_SERVICE_URL": PRODUCT_URL,
                "INVENTORY_SERVICE_URL": INVENTORY_URL,
            },
            tmp_dir,
        ),
    ]
    try:
        _wait_healthy(PRODUCT_URL)
        _wait_healthy(INVENTORY_URL)
        _wait_healthy(ORDER_URL)

        tunnels = start_tunnels(
            {"product": PRODUCT_PORT, "inventory": INVENTORY_PORT, "order": ORDER_PORT}, tmp_dir
        )
        public = {tunnel.name: tunnel.url for tunnel in tunnels}
        reachable = _verify_public_urls(public)
        if public:
            print("\n" + "=" * 72)
            print("  The live test stack is public (temporary trycloudflare tunnels).")
            print("  Open these in your browser to watch/follow along with the UI:")
            for tunnel in tunnels:
                print(f"    {tunnel.name:10s} {tunnel.url}/docs")
            if not reachable:
                print(
                    "  WARNING: public URLs did not answer within 60s — outbound 7844 is "
                    "probably blocked by this network's egress proxy (see the trycloudflare "
                    "docs / cloudflared pre-check). The browser test itself ran against the "
                    "local stack and is unaffected. Use VS Code port-forwarding or a "
                    "non-restricted network to view it."
                )
            if os.getenv("BROWSER_VIEW_PAUSE_SECONDS", "0") != "0":
                print("  (hold the live stack open after the test with BROWSER_VIEW_PAUSE_SECONDS, e.g. 300)")
            print("=" * 72 + "\n", flush=True)

        yield {
            "product": PRODUCT_URL,
            "inventory": INVENTORY_URL,
            "order": ORDER_URL,
            "api_key": API_KEY,
            "product_port": str(PRODUCT_PORT),
            "inventory_port": str(INVENTORY_PORT),
            "order_port": str(ORDER_PORT),
            "public": public,
            "tunnels": tunnels,
        }
    finally:
        stop_all(tunnels)
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        for child in tmp_dir.iterdir():
            child.unlink(missing_ok=True)
        tmp_dir.rmdir()

