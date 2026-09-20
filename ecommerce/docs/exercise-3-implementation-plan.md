# Exercise 3 — Custom Agent → Order Service

**Goal:** a reusable `Backend API Expert` custom agent, then use it to produce `services/order_service`
— the first service that talks to the other two over HTTP.

## Step 1 — Create the agent file

`.github/agents/backend-api-expert.agent.md` (workspace-scoped so it ships as a lab deliverable).

Frontmatter:

```yaml
---
description: Backend API expert for designing REST services, clean architecture, validation, and error handling.
tools: ['search/codebase', 'search', 'edit/editFiles', 'execute/getTerminalOutput', 'execute/runInTerminal', 'read/terminalLastCommand', 'read/terminalSelection', 'read/problems', 'vscodeTasks/problems', 'execute/testFailure','vscodeGeneral/testFailure']
---
```

Body covers the four spec responsibilities, written as a **standing persona** rather than a one-shot task —
that is the contrast with Exercise 2's prompt file:

- **Design REST APIs** — resource-oriented paths, correct status codes, request/response models per operation.
- **Recommend clean architecture** — routes stay thin; HTTP clients, persistence, and business rules live in
  separate modules behind interfaces the tests can substitute.
- **Improve validation** — push rules into Pydantic `Field`/`field_validator`; validate cross-service
  preconditions in one place, not scattered through handlers.
- **Suggest logging and error handling** — structured logging at service boundaries, and a documented mapping
  from upstream failures to this service's status codes.

Like the prompt file, it does *not* restate repo-wide rules from
[copilot-instructions.md](../.github/copilot-instructions.md).

## Step 2 — Run the agent for Order Service

Ask it to generate the Order Service, then exercise the "refine it using follow-up prompts" half of the
exercise with at least two follow-ups (e.g. *"add logging around the inventory call"*, *"what happens if the
inventory PATCH fails after we've already validated the product?"*).

## Step 3 — Expected output

```
services/order_service/
  requirements.txt          fastapi, uvicorn, pydantic, httpx, pytest
  app/__init__.py
  app/main.py               FastAPI app + router + /health
  app/config.py             PRODUCT_SERVICE_URL / INVENTORY_SERVICE_URL from env, with defaults
  app/clients.py            ProductClient + InventoryClient (httpx, 5s timeout)
  app/models.py             OrderCreate / Order
  app/routes.py             3 endpoints
  app/storage.py            OrderRepository (in-memory dict, .clear() for tests)
  tests/__init__.py
  tests/test_orders.py
```

Endpoints (per spec):

| Method | Path | Codes |
|---|---|---|
| POST | `/orders` | 201, 404, 409, 422, 502 |
| GET | `/orders` | 200 |
| GET | `/orders/{id}` | 200, 404 |

Fields: `id: str` (server-generated UUID), `customerId: str`, `productId: str`,
`quantity: int = Field(gt=0)`, `unitPrice: float`, `totalPrice: float`, `status: str`,
`createdAt: datetime`. `OrderCreate` carries only `customerId`, `productId`, `quantity` — price, status,
and timestamps are server-owned.

Order workflow in `POST /orders`:

1. `GET {product}/products/{productId}` — 404 upstream → `404` here.
2. `GET {inventory}/inventory/{productId}` — 404 upstream → `404` here; `quantity < requested` → `409`.
3. `PATCH {inventory}/inventory/{productId}` with the decremented quantity.
4. Persist the order with `unitPrice` snapshotted from the product and `status="CONFIRMED"`.
5. Return `201` with the order confirmation.

Error mapping: any upstream timeout or unexpected non-2xx becomes `502` with a JSON `detail` naming the
failing dependency.

## Step 4 — Verify

`pip install -r requirements.txt` then `pytest`, and run on port 8003 per the [README](../README.md).
Tests substitute fake `ProductClient` / `InventoryClient` implementations via FastAPI
`dependency_overrides` — no real network calls, no new test dependency. Cover: happy path, unknown product
(404), insufficient stock (409), upstream timeout (502), and `quantity=0` (422).

## Decisions worth confirming

1. **Inventory decrement is read-then-write** — two calls, not atomic. Acceptable for the lab; note it as a
   known race in the code rather than inventing a reservation protocol.
2. **No compensating rollback** — if step 4 fails after step 3 succeeded, inventory has already been reduced.
   Log it loudly; a saga/outbox is out of scope.
3. **Unknown product is `404`, insufficient stock is `409`** — matching the status-code table in
   [copilot-instructions.md](../.github/copilot-instructions.md).
4. **`unitPrice` is snapshotted at order time** — later product price changes do not rewrite past orders.
5. **No cancel/delete endpoint** — the spec lists only the three endpoints above.
