# Hardening Implementation Plan — Post-Extension Improvements

**Goal:** close the gaps identified after the [extension plan](extension-implementation-plan.md) was fully
implemented and Docker-verified, without changing any REST contract already agreed in
[api-design.md](sdlc/api-design.md) and the [README](../README.md) endpoint tables.

Phases are ordered smallest-risk-first. Each is independently shippable. Phases 9–11 change runtime
behavior; Phase 12–13 change build/CI only.

## Phase 9 — Dockerfile and compose hardening ✅ implemented

Shipped as described above. Verified: three images build on `python:3.14-slim`, PID 1 runs as
`appuser` (uid 1000) in all three containers, a write to `/etc` returns `Read-only file system`, a write
to `/data` succeeds, and the full cross-container E2E passes on the hardened stack.

The extension plan's own Phase 3 rationale ("pin the runner... so lint and runtime agree") was only half
honored: CI ran Python 3.14 (per `ruff.toml`'s `target-version = "py314"`) but the three Dockerfiles
shipped `python:3.12-slim`. CI passing did not prove the deployed interpreter.

- **Align base image to 3.14** across all three service Dockerfiles: `FROM python:3.14-slim`.
- **Run unprivileged.** Add a non-root `appuser`; chown the `/data` volume mount so the SQLite file is
  writable. SQLite and uvicorn need no SUID capability, so this is free.
- **Compose hardening.**
  - `read_only: true` root filesystem per service, with `/data` as the single writable bind.
  - `restart: on-failure` on all three services.
  - Document (comment) that ports are published on all interfaces for the local dev workflow; production
    deployments should scope them. Keep publishing for now so the MCP stdio config and manual E2E keep
    working.
- **No code change** is expected: the app already writes only under `DATABASE_URL` (i.e. `/data`), so a
  read-only root must be satisfiable.

**Verify:** `docker compose build --no-cache` succeeds for all three images; `docker compose up -d` brings
all services healthy; the full cross-container E2E (product → inventory → order) still passes; a `ps aux`
inside a container shows the app running as `appuser`; writing to a non-`/data` path from the app user
fails.

## Phase 10 — Retried, key-protected inventory `PATCH` ✅ implemented

Analysis of [clients.py](../services/order_service/app/clients.py): GET retry (`_get_with_retry`) already
retries `httpx.RequestError` **and** upstream `5xx` (the loop only terminates early on `status_code < 500`),
so GETs need no change. The remaining one-attempt call is the inventory `PATCH` in
`InventoryClient._adjust_quantity`, which is correct *by design* for non-error responses (a retried delta
double-decrements stock) — but on a **transport error** (`httpx.RequestError`: connect, timeout, mid-body
read failure) the request may or may not have reached Inventory Service. Phase 5's `Idempotency-Key`
forwarding is exactly what makes one guarded retry safe in that ambiguous case: Inventory replays recorded
keys with the stored snapshot, so a duplicate delta cannot land.

This phase makes one concrete change:

- Retry the inventory `PATCH` **at most one extra time**, and **only** on `httpx.RequestError` (connect /
  timeout / read), and **only** when an `Idempotency-Key` is present — creation and cancellation both always
  send one — forwarding the *same* key on the retry, with a short backoff consistent with the GET retries.
  A `5xx` *response* from `PATCH` is **not** retried: the idempotency key covers the ambiguous
  *no-response* case; an explicit `5xx` still surfaces as `502` per the cross-service rules and the
  caller's own key-based retry.
- Leave GET retry behavior exactly as-is.

Shipped in [`clients.py`](../services/order_service/app/clients.py) as `_patch_with_key_protected_retry`,
invoked from `InventoryClient._adjust_quantity`. Verified by four focused tests in the order suite: retried
once with the *same* key after a transport `ReadError`, raising `UpstreamUnavailableError` after exactly two
attempts when the retry also fails, single-attempt without an `Idempotency-Key`, and single-attempt on a `5xx`
response — plus the pre-existing GET-retry cases.

**Verify:** new tests in the order suite: (a) a `PATCH` that raises `ReadError` on the first attempt and
succeeds on the second with the same `Idempotency-Key` results in a single successful adjustment; (b) a
`PATCH` that always raises `ReadError` raises `UpstreamUnavailableError` after exactly two attempts; (c) a
`PATCH` without an idempotency key (no such path today, asserted defensive) is single-attempt; (d) a `5xx`
`PATCH` is single-attempt.

## Phase 11 — SQLite busy-timeout for file-backed URLs ✅ implemented

Shipped as `busy_timeout_for()` + classification helpers in each service's `db.py`, applied only for
file-backed SQLite URLs. Verified by `tests/test_db_config.py` in each service asserting the classification
and that the engine still opens connections; all three suites green.

The Phase 4 deviation note defers Postgres but SQLite's default 5s busy-wait is applied only via the
driver default; making it explicit prevents `SQLITE_BUSY` flakes under the concurrent test load and in
long-lived compose deployments where the healthcheck reader and the app writer share a file.

- In each service's [db.py](../services/inventory_service/app/db.py), set `connect_args["timeout"] = 30.0`
  for **file-backed** SQLite URLs only (not `:memory:` — in-memory + `StaticPool` never blocks, and a
  30s timeout there would mask a logic error in tests).
- Keep `check_same_thread` and `poolclass` behavior unchanged.

**Verify:** existing concurrency tests still pass (they already exercise this); add a unit test per
service asserting the engine's connect args include `timeout=30.0` for a file URL and that the
in-memory test URL path is unchanged.

## Phase 12 — Idempotency record TTL/pruning ✅ implemented

Shipped as described, with one implementation note: SQLite rejects a non-constant default on `ADD COLUMN`
(so `DEFAULT (datetime('now'))` cannot ride on the `ALTER TABLE`), so `ensure_schema()` adds the timestamp
column nullable and backfills it with a SQL `UPDATE`. `IDEMPOTENCY_TTL_SECONDS` defaults to 86400 in both
services' `config.py`.

Phase 5 made idempotency records persistent, which is also unbounded: `applied_inventory_adjustments`
(Inventory) and `order_idempotency` + claims (Order) grow one row per request key forever. Long-lived
compose deployments with durable volumes will accumulate them.

Design constraints from the existing code:

- The Order Service already has a **lease/polling** mechanism (`IDEMPOTENCY_LEASE_SECONDS = 60`,
  `IDEMPOTENCY_WAIT_SECONDS = 65`) — an in-flight claim must never be pruned. Pruning may only remove
  *settled* records (order created, or adjustment applied).
- A replay that arrives *within* the TTL must return the stored snapshot; after the TTL, a replay simply
  behaves like a new request (the key is gone) — callers must accept that a very old replay may create a
  second order. 24h TTL is the floor where this is acceptable for a training-grade system and is still
  weeks longer than any sane client retry window.

- Add `IDEMPOTENCY_TTL_SECONDS` (default `86400`, env-overridable) per service.
- **Inventory:** `AppliedInventoryAdjustmentORM` gains `appliedAt: datetime`; `InventoryRepository.update`
  prunes rows older than the TTL **as a side effect of each `update` call** (a single `DELETE ... WHERE
  appliedAt < :cutoff`, batched, no cron). Replays within the TTL are unchanged.
- **Order:** `OrderIdempotencyORM` gains `createdAt` if not present; `create_order` prunes settled
  records older than the TTL before claiming; claims never qualify for pruning.
- Migration concern: this is the **first intentional schema change** under running data, so per the
  extension plan's decision #6 it qualifies for Alembic — but since the change is purely additive and
  `create_all()` bootstraps new volumes, the pragmatic move is: additive column + `create_all()` for new
  volumes + a tiny one-shot `ALTER TABLE ... ADD COLUMN` guarded by a pragma check for existing volumes.
  Document this as the precedent for when full Alembic is introduced.

**Verify:** new tests: (a) an inventory adjustment replayed within the TTL returns the stored snapshot;
(b) a record backdated beyond the TTL is pruned on the next `update` and a same-key request is treated as
new; (c) the in-flight order claim path is unaffected by pruning; (d) an **existing-volume upgrade** test
that creates the old schema on a file DB, applies the one-shot migration, and reads/writes successfully.

## Phase 13 — Coverage floor + compose smoke in CI ✅ implemented

Coverage floors set from measured values (product 95%, inventory 94%, order 94%, MCP 97%) to
`90 / 90 / 90 / 95`. `scripts/compose_smoke.sh` is the manual Docker verification codified; the
`docker-smoke` CI job runs `docker compose config` then the script.

The extension plan's CI (Phase 3) runs `pytest` per service but nothing measures coverage, and nothing in
CI exercises the *composed* deployment — exactly the gap the manual Docker verification closed by hand.

- **Coverage:** added `pytest-cov` to `requirements-dev.txt`; each service's suite runs with
  `--cov=app --cov-report=term --cov-fail-under=<floor>`, with per-service floors pinned in the CI matrix
  after measuring: product 95%, inventory 94%, order 94%, MCP 97% → floors **90 / 90 / 90 / 95**. The
  floors sit a few points *below* the measured coverage so legitimate new-but-untested lines get caught
  rather than failing immediately, while a meaningful regression still turns CI red.
- **Compose smoke:** a second CI job `docker-smoke` that (a) `docker compose up -d --build`, (b) polls
  `/health` on all three, (c) runs the product → inventory → order E2E with curl + jq asserting the stock
  delta, (d) replays the `Idempotency-Key` asserting unchanged stock, (e) restarts the containers and
  asserts data survived, (f) `docker compose down`. Runs on push to `main` and PRs (like the existing
  jobs). A shell script under `scripts/compose_smoke.sh` keeps the workflow legible; the workflow only
  calls it.
- The smoke script is also runnable locally (`scripts/compose_smoke.sh`), which is the manual Docker
  verification codified.

**Verify:** CI job definitions render correctly; locally, `scripts/compose_smoke.sh` exits 0 on the
current code and exits non-zero when a deliberate fault (e.g. wrong `API_KEY` in the script) is injected
and then reverted.

## Explicitly not doing (and why)

- **Circuit breaker** — still deferred, as in extension plan Phase 5: with bounded retries, per-key
  idempotency, and 5s timeouts, a dead upstream costs at most ~5s per order attempt plus two GET retry
  delays. A breaker adds state and its own failure modes; add it when p99 evidence says the wait budget
  hurts.
- **`/metrics` (Prometheus)** — no scrape target exists in this topology yet (no Grafana/Prometheus in
  compose, no production). Instrumenting endpoints nobody scrapes is premature; the JSON logs +
  correlation already answer "which of the three failed?" for the current operating envelope.
- **Shared OpenAPI contract test** — the `Upstream*` models in Order Service are deliberately a *consumer*
  copy; a cross-service schema-diff tool would couple the services' release cycles, contradicting the
  repo's isolation rule. Identifier-mismatch validation in `clients.py` already catches the drift that
  actually matters.
- **MCP over stdio in the smoke job** — the stdio transport needs an MCP client harness in CI; the MCP
  integration suite (54 tests) already boots real services and drives the server over stdio, which is the
  same contract the compose deployment exposes.
