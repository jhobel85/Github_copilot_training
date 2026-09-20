# SDLC Exercise — Review Findings

**Phase:** Review · **Slice:** Order cancellation
**Reviewed:** [routes.py](../../services/order_service/app/routes.py),
[clients.py](../../services/order_service/app/clients.py),
[test_orders.py](../../services/order_service/tests/test_orders.py) — the Coding + Testing diff for
`POST /orders/{order_id}/cancel`.

## Bugs

1. `routes.py` — `cancel_order`, inventory-restore step — Read-then-write, not atomic: a concurrent
   create/cancel for the same product between the `GET /inventory/{productId}` and the restoring
   `PATCH` can race and leave the stored quantity wrong. This mirrors the same gap already documented in
   `create_order` ([order-creation-sequence.md](order-creation-sequence.md)), so it is an inherited risk,
   not a regression introduced by this slice — but the slice doubles the number of code paths exposed to it.
   **Why it matters:** under concurrent load, inventory can end up over- or under-counted with no error
   surfaced to either caller. **Suggested fix:** replace the read-then-set-absolute PATCH with a delta-based
   endpoint on Inventory Service (e.g. `PATCH /inventory/{id}/adjust {"delta": -2}` /
   `{"delta": +2}`), so the adjustment is computed and applied atomically server-side instead of
   client-computed from a stale read.

## Improvements

1. `services/order_service/app/routes.py:55-57,112` — `ruff check` flags `B008` (function call in an
   argument default) on every `Depends(...)` parameter, including the new `cancel_order` signature. This is
   FastAPI's idiomatic dependency-injection pattern, already used before this slice, and `B008` doesn't
   recognize it as safe. **Why it matters:** the lint output is noisy on every route file, which will bury
   real findings once the Exercise 4 hook is in daily use. **Suggested fix:** add
   `lint.ignore = ["B008"]` to the repo-root `ruff.toml`.
2. `services/order_service/app/models.py` — `Order.status` is a bare `str`; `cancel_order` now assigns
   `order.status = "CANCELLED"` directly, and `create_order` sets `"CONFIRMED"`, but nothing stops a typo'd
   or unexpected status value from being stored. **Why it matters:** an invalid status silently corrupts
   state instead of failing loudly. **Suggested fix:** change the field to
   `Literal["CONFIRMED", "CANCELLED"]` and enable `model_config = ConfigDict(validate_assignment=True)` so
   `order.status = ...` is validated the same way constructor arguments already are.

## REST API design conformance

1. `services/order_service/app/routes.py` — `POST /orders/{order_id}/cancel` — the path contains a verb
   (`cancel`), which conflicts with the explicit convention in
   [copilot-instructions.md](../../.github/copilot-instructions.md): "Paths use plural resource nouns
   ... and contain no verbs." **Why it matters:** this is a written project convention, not a style
   preference, and the new endpoint breaks it in a way `/products`, `/inventory`, and the rest of `/orders`
   do not. **Suggested fix:** two options, either is reasonable — (a) model cancellation as a state
   transition on the resource itself: `PATCH /orders/{order_id}` accepting a small
   `OrderStatusUpdate` model (mirrors the existing `PATCH /inventory/{productId}` pattern), or (b) keep
   `/cancel` as a documented, deliberate exception (like the existing `/health` route) if a dedicated
   action endpoint is preferred for discoverability. This needs a decision, not a default — see the triage
   note below.

## Security concerns

No findings. The endpoint takes no client-supplied request body (only the `order_id` path parameter), and
the `productId` used for the upstream inventory call is read from the already-validated, server-stored
`Order`, not from new client input. Error details returned to the caller (`exc.detail`) reuse the same
upstream-message passthrough as `create_order`, which is an existing, unchanged pattern in this codebase.

---
## Triage

All four findings were **accepted and fixed**. Nothing was deferred or rejected.

| # | Finding | Decision | Where it landed |
|---|---|---|---|
| Bug 1 | Non-atomic inventory read-then-write | **Accepted — fixed** | `inventory_service/{models,storage,routes}.py`, `order_service/app/clients.py` |
| Improvement 1 | `B008` lint noise on `Depends()` | **Accepted — fixed** | `ruff.toml` |
| Improvement 2 | `Order.status` is an unvalidated `str` | **Accepted — fixed** | `order_service/app/models.py` |
| REST 1 | Verb in `POST /orders/{id}/cancel` | **Accepted — fixed, option (a)** | `order_service/app/{models,routes}.py` |

### Bug 1 — how it was fixed

The suggested fix proposed a dedicated `PATCH /inventory/{id}/adjust` endpoint, but that would have
introduced a verb into a path while the very next finding is about removing one. Instead, the existing
`PATCH /inventory/{productId}` gained an **optional `quantityDelta` field**:

- Inventory Service resolves the delta against its own stored quantity (`InventoryRepository.update`), so no
  caller ever computes an absolute from a stale read.
- A delta that would drive stock below zero raises `InsufficientInventoryError` → `409` with an explanatory
  `detail`, matching the repo's existing 409 convention.
- `quantity` and `quantityDelta` are mutually exclusive (`model_validator` → `422`); absolute `quantity`
  updates still work unchanged, so this is additive.
- `InventoryClient._set_quantity` became `_adjust_quantity(product_id, delta)`; `reduce_inventory` and
  `restore_inventory` now take the *magnitude* to move and send `-n` / `+n`.
- `cancel_order`'s pre-read `GET /inventory/{productId}` disappeared entirely — it existed only to compute
  the absolute. `create_order` keeps its `GET` purely as a friendly pre-flight check; correctness now rests
  on the `PATCH`, which also maps a late `409` back to the caller.

### REST 1 — decision

**Option (a) was chosen:** `POST /orders/{order_id}/cancel` → `PATCH /orders/{order_id}` with an
`OrderStatusUpdate` body (`status: Literal["CANCELLED"]`). Rationale: the repo's no-verbs rule is written
down as a convention rather than a preference, `PATCH /inventory/{productId}` already establishes the
state-transition-via-PATCH shape in this codebase, and typing `status` as a `Literal` gets the "unsupported
transition" case to `422` through Pydantic instead of a hand-written check. Option (b) was rejected because
`/health` is an operational endpoint outside the resource model, which `/cancel` is not.

### Verification

`ruff format` + `ruff check` clean across all services; `pytest` green in all three: product 10, inventory 15
(+4 for `quantityDelta`), order 16 (+2 for the `422` status and the late-`409` race path).
