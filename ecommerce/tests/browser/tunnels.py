"""Account-less Cloudflare quick tunnels that expose the test stack to the web.

Quick tunnels (``cloudflared tunnel --url ...``) need no Cloudflare account or
config: each one mints a random ``*.trycloudflare.com`` URL reaching the
requested local port. The browser-test fixture starts one per service so the
walkthrough can be watched in a real browser on any machine with zero manual
setup (no port forwarding, no SSH -L), and stops them at session end.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

_CLOUDFLARE_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def cloudflared_binary() -> str | None:
    """Locate the cloudflared binary (PATH, then ``~/.local/bin``)."""
    found = shutil.which("cloudflared")
    if found:
        return found
    candidate = Path(os.path.expanduser("~")) / ".local" / "bin" / "cloudflared"
    return str(candidate) if candidate.exists() else None


@dataclass
class Tunnel:
    """One running quick tunnel: local origin -> minted public URL."""

    name: str
    local_url: str
    url: str
    process: subprocess.Popen[bytes]
    log_path: Path

    def stop(self) -> None:
        if self.process.poll() is None:
            try:
                urllib.request.urlopen(f"{self.url}/health", timeout=2)
            except OSError:
                pass
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()


def start_tunnels(name_to_port: dict[str, int], tmp_dir: Path, timeout: float = 45.0) -> list[Tunnel]:
    """Start a quick tunnel per service; return the started ``Tunnel`` objects.

    Best-effort by design: a missing binary or offline machine yields an empty
    (or partial) list plus a stderr warning, never a test-suite failure — the
    walkthrough itself only requires the local stack.
    """
    binary = cloudflared_binary()
    if binary is None:
        print(
            "[tunnels] cloudflared not found; test stack stays local-only. "
            "Install with: curl -L -o ~/.local/bin/cloudflared "
            "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 "
            "&& chmod +x ~/.local/bin/cloudflared",
            file=sys.stderr,
        )
        return []

    tunnels: list[Tunnel] = []
    for name, port in name_to_port.items():
        log_path = tmp_dir / f"cloudflared-{name}.log"
        log_file = log_path.open("w", encoding="utf-8")
        log_file.write(f"# quick tunnel for {name} -> 127.0.0.1:{port}\n")
        log_file.flush()
        process = subprocess.Popen(
            [binary, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        tunnels.append(Tunnel(name, f"http://127.0.0.1:{port}", "", process, log_path))

    started: list[Tunnel] = []
    for tunnel in tunnels:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if tunnel.process.poll() is not None:
                break
            match = _CLOUDFLARE_URL.search(tunnel.log_path.read_text(encoding="utf-8", errors="replace"))
            if match:
                tunnel.url = match.group(0)
                started.append(tunnel)
                break
            time.sleep(0.5)
        else:
            print(
                f"[tunnels] no URL minted for '{tunnel.name}' within {timeout:.0f}s; "
                "continuing without it",
                file=sys.stderr,
            )
            tunnel.stop()
    return started


def stop_all(tunnels: Iterable[Tunnel]) -> None:
    for tunnel in tunnels:
        try:
            tunnel.stop()
        except Exception as exc:  # noqa: BLE001 - teardown must never mask results
            print(f"[tunnels] stopping '{tunnel.name}' failed: {exc}", file=sys.stderr)
