# Exercise 4 — Hooks → Post-Edit Quality Gate

**Goal:** a workspace-scoped hook that runs automatically after the agent edits a Python file — formats it,
lints it, and runs the owning service's tests — then use it while generating a new endpoint and observe the
feedback.

VS Code hooks are deterministic shell commands at agent lifecycle points (`.github/hooks/*.json`), unlike
instructions/prompts/agents which only *guide* behavior. `PostToolUse` is the event that fires after a tool
call succeeds, which is what "runs automatically after code generation" means here.

Agent hooks are a **Preview** VS Code feature and can be disabled by enterprise policy — if nothing fires in
Step 4, check for that before assuming the script is broken.

## Step 1 — Add the tooling the hook depends on

Add `ruff` (format + lint in one dependency) as a repo-level dev dependency — it isn't installed yet and none
of the three services currently pull in a formatter/linter.

`requirements-dev.txt` (repo root):
```
ruff>=0.8
```
The active interpreter is Python 3.14.6, so pin `target-version` to match; confirm during `pip install` that
the installed `ruff` actually recognizes `py314` and bump the floor if it doesn't.

`ruff.toml` (repo root, so it applies to all three services without per-service config):
```toml
line-length = 110
target-version = "py314"
```
Measured against the current codebase: 110 is the longest real source line, so this won't trigger a mass
reformat on first run. `product_service` has its own `.venv/` (the other two don't); ruff excludes `.venv`
by default and it's already in [.gitignore](../.gitignore), so no extra exclude config is needed.

`pip install -r requirements-dev.txt` once, globally.

## Step 2 — Create the hook script

`.github/hooks/scripts/post_edit_quality.py` — a Python script (not `.ps1`/`.sh`) so the same hook command
works regardless of OS.

Logic:
1. Read the JSON object VS Code passes on stdin. Pull `tool_name` and `tool_input`. On the very first run,
   also dump the raw payload to `.github/hooks/scripts/.debug.log` (gated behind an env var, e.g.
   `POST_EDIT_HOOK_DEBUG=1`) to confirm the actual field names/shape before relying on them — the
   `tool_input["replacements"][].filePath` shape for `multi_replace_string_in_file` below is an assumption
   until checked against a real payload.
2. VS Code ignores hook `matcher` values (per the hooks docs), so filter in the script: only continue if
   `tool_name` is one of `create_file`, `replace_string_in_file`, `multi_replace_string_in_file`. Anything
   else exits `0` immediately with no output.
3. Extract the edited path(s): `tool_input["filePath"]` for the single-file tools, or
   `[r["filePath"] for r in tool_input["replacements"]]` for the multi-replace tool. Keep only `*.py` paths.
4. If no Python files were touched, exit `0` with no output.
5. For each touched file, walk up to the nearest ancestor containing `requirements.txt` to find its owning
   service directory (e.g. `services/product_service`). Also check for `<service_dir>/.venv` — only
   `product_service` has one today — and prefer `.venv/Scripts/python.exe` (Windows) /
   `.venv/bin/python` (POSIX) over the global interpreter when it exists, so validation runs against the
   same environment the service actually uses.
6. Run, capturing output:
   - `ruff format <file>`
   - `ruff check --fix <file>`
   - `pytest -q`, once per distinct owning service directory touched, invoked **with `cwd` set to that
     service directory** (not the whole repo) — required because the tests do `from app.main import app`,
     which only resolves relative to the service root.
7. Print one JSON object to stdout summarizing what ran:
   ```json
   {"continue": true, "systemMessage": "ruff: formatted 1 file, 0 lint issues | pytest (product_service): 9 passed"}
   ```
   Exit `0` either way (see Decision 1 for why this stays non-blocking).

## Step 3 — Create the hook config

`.github/hooks/post-edit-quality.json`:
```json
{
  "hooks": {
    "PostToolUse": [
      {
        "type": "command",
        "command": "python .github/hooks/scripts/post_edit_quality.py",
        "cwd": "c:\\Users\\Administrator\\Documents\\ecommerce",
        "timeout": 60
      }
    ]
  }
}
```
The hooks reference documents `cwd` as configurable but not its default, so pin it explicitly to the
workspace root rather than assume the relative `command` path resolves correctly — verify this in Step 5 by
running the exact same command from a different starting directory.

Saving this file is enough — VS Code loads `.github/hooks/*.json` automatically, no reload required.

## Step 3a — Protect the hook script from agent edits

The agent that this hook validates can also edit `post_edit_quality.py` itself, then have its own edit
auto-approved and executed on the next tool call. Add to `.vscode/settings.json`:
```json
{
  "chat.tools.edits.autoApprove": {
    ".github/hooks/**": false
  }
}
```
so changes to the hook require manual approval, per the hooks doc's safety guidance.

## Step 4 — Trigger it

Ask any agent to generate a new endpoint, e.g. *"Add `GET /products/category/{category}` to Product Service,
returning all products in that category"*. When the agent edits `routes.py` (and any other `.py` file), the
hook fires afterward; watch for:
- The `systemMessage` surfaced in the chat turn.
- Full command output in the Output panel → **GitHub Copilot Chat Hooks** channel, or via
  **Developer: Show Agent Debug Logs**.

## Step 5 — Verify the hook directly

Before trusting a live agent run, pipe a synthetic `PostToolUse` payload at the script to confirm it works in
isolation:
```powershell
'{"hook_event_name":"PostToolUse","tool_name":"replace_string_in_file","tool_input":{"filePath":"c:\\Users\\Administrator\\Documents\\ecommerce\\services\\product_service\\app\\routes.py"}}' | python .github/hooks/scripts/post_edit_quality.py
```
Confirm it prints a single valid JSON line and exits `0`.

## Decisions worth confirming

1. **Non-blocking feedback, not enforcement** — the hook reports via `systemMessage` and always exits `0`,
   it never fails the tool call. That matches the exercise's "observe the feedback from the hook" framing.
   If the team wants a real quality gate, switch the pytest-failure path to exit code `2` (blocking error,
   shown to the model) instead of a plain message.
2. **Matching is done in-script, not via hook `matcher`** — VS Code parses but ignores `matcher` values, so
   the allow-list of edit-tool names lives in `post_edit_quality.py` itself.
3. **`ruff` over `black` + `flake8`** — one dependency covers both the "format" and "lint" suggested actions
   from the spec.
4. **Scoped to the touched service** — `pytest` runs only for the service directory containing the edited
   file(s), invoked with `cwd` set to that directory and its own `.venv` interpreter when one exists (only
   `product_service` has one today), not the whole repo, so the hook stays well under its timeout and
   validates against the right environment.
5. **Config lives in `.github/hooks/`** — workspace-scoped and committed, so it ships as the lab's "working
   hook" deliverable like the prompt file and custom agent from Exercises 2–3.
6. **`requirements-dev.txt` at the repo root breaks the per-service `requirements.txt` convention** —
   accepted deliberately: the hook tooling isn't part of any one service's runtime dependencies.
