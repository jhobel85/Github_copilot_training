"""PostToolUse hook: format, lint, and test the service(s) touched by the last edit tool call."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

EDIT_TOOLS = {"create_file", "replace_string_in_file", "multi_replace_string_in_file"}
REPO_ROOT = Path(__file__).resolve().parents[2]
DEBUG_LOG = Path(__file__).resolve().parent / ".debug.log"
SUBPROCESS_TIMEOUT_SECONDS = 45


def _read_payload() -> dict:
    raw = sys.stdin.read()
    if os.environ.get("POST_EDIT_HOOK_DEBUG"):
        DEBUG_LOG.write_text(raw, encoding="utf-8")
    try:
        return json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}


def _extract_paths(tool_name: str, tool_input: dict) -> list[Path]:
    if tool_name in ("create_file", "replace_string_in_file"):
        raw_paths = [tool_input.get("filePath")]
    elif tool_name == "multi_replace_string_in_file":
        raw_paths = [r.get("filePath") for r in tool_input.get("replacements", [])]
    else:
        raw_paths = []
    return [Path(p) for p in raw_paths if p and p.endswith(".py")]


def _find_service_dir(path: Path) -> Path | None:
    for parent in path.parents:
        if (parent / "requirements.txt").is_file():
            return parent
        if parent == REPO_ROOT:
            break
    return None


def _service_python(service_dir: Path) -> str:
    venv_python = (
        service_dir / ".venv" / "Scripts" / "python.exe"
        if os.name == "nt"
        else service_dir / ".venv" / "bin" / "python"
    )
    return str(venv_python) if venv_python.is_file() else sys.executable


def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SECONDS, check=False
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def main() -> int:
    payload = _read_payload()
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}

    if tool_name not in EDIT_TOOLS:
        return 0

    py_paths = [p for p in _extract_paths(tool_name, tool_input) if p.is_file()]
    if not py_paths:
        return 0

    ruff = shutil.which("ruff")
    formatted = 0
    dirty_files: list[str] = []
    services_touched: dict[Path, str] = {}

    for path in py_paths:
        service_dir = _find_service_dir(path)
        if service_dir is not None:
            services_touched.setdefault(service_dir, _service_python(service_dir))
        if ruff:
            _run([ruff, "format", str(path)])
            formatted += 1
            code, _ = _run([ruff, "check", "--fix", str(path)])
            if code != 0:
                dirty_files.append(path.name)

    test_summaries = []
    for service_dir, python_exe in services_touched.items():
        code, output = _run([python_exe, "-m", "pytest", "-q"], cwd=service_dir)
        last_line = next((line for line in reversed(output.splitlines()) if line.strip()), "no output")
        status = "passed" if code == 0 else "FAILED"
        test_summaries.append(f"pytest ({service_dir.name}): {status} \u2014 {last_line}")

    parts = []
    if ruff:
        lint_state = (
            "no unresolved issues" if not dirty_files else f"unresolved issues in {', '.join(dirty_files)}"
        )
        parts.append(f"ruff: formatted {formatted} file(s), {lint_state}")
    else:
        parts.append("ruff not found on PATH \u2014 install requirements-dev.txt")
    parts.extend(test_summaries)

    print(json.dumps({"continue": True, "systemMessage": " | ".join(parts)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
