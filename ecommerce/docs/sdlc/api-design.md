# SDLC Exercise — API Design

**Phase:** Design · **Slice:** Order cancellation
**Input:** [user-stories.md](user-stories.md) · **Output consumed by:** Coding, Testing

## Endpoint table

| Method | Path | Request model | Response model | Status codes | Satisfies |
|---|---|---|---|---|---|
| GET | `/products?limit&offset` | — | `list[Product]` | `200`, `401`, `422` | US-01 |
| GET | `/products/{id}` | — | `Product` | `200`, `401`, `404` | US-01 |
| POST | `/products` | `ProductCreate` | `Product` | `201`, `401`, `422` | US-02 |
| GET | `/inventory?limit&offset` | — | `list[InventoryItem]` | `200`, `401`, `422` | US-03 |
| GET | `/inventory/{productId}` | — | `InventoryItem` | `200`, `401`, `404` | US-03 |
| POST | `/inventory` | `InventoryCreate` | `InventoryItem` | `201`, `401`, `409`, `422` | US-03 |
| PATCH | `/inventory/{productId}` | `InventoryUpdate` | `InventoryItem` | `200`, `401`, `404`, `409`, `422` | US-04 |
| POST | `/orders` | `OrderCreate` | `Order` | `201`, `401`, `404`, `409`, `422`, `502` | US-05 |
| GET | `/orders/{id}` | — | `Order` | `200`, `401`, `404` | US-06 |
| **PATCH** | **`/orders/{id}`** | **`OrderStatusUpdate`** | `Order` | `200`, `401`, `404`, `409`, `422`, `502` | **US-07** |
| GET | `/orders?limit&offset` | — | `list[Order]` | `200`, `401`, `422` | US-08 |

All rows above `PATCH /orders/{id}` already exist; it is the only new endpoint this slice adds.

## Phase 6 authentication and pagination

- All product, inventory, and order resource endpoints require `X-API-Key` matching the `API_KEY`
  environment variable. Missing or incorrect keys return `401`. `/health` remains unauthenticated.
- The local-only default is `local-development-api-key`; compose and the VS Code MCP configuration set the
  same value explicitly. Deployments must override it.
- `GET /products`, `GET /inventory`, and `GET /orders` accept `limit` (default `50`, minimum `1`, maximum
  `100`) and `offset` (default `0`, minimum `0`). FastAPI query constraints return `422` for invalid values.
- Pagination order is stable: product id for products, product id for inventory, and creation time then id
  for orders.
- Order Service authenticates every Product and Inventory upstream request. The MCP server authenticates
  every REST request, and its three `list_*` tools expose and pass through `limit` and `offset`.

## Phase 7 observability

- Every API accepts an optional `X-Request-ID` header on resource and health requests. A missing value is
  replaced with a generated UUID, and every response returns the effective value in `X-Request-ID`.
- The active request ID is stored in context-local state and added to every application log record, keeping
  concurrent requests isolated.
- Order Service forwards the active request ID on every Product and Inventory `GET` and Inventory `PATCH`,
  alongside the existing API key and optional idempotency key.
- All services configure one-line JSON logging. Every record contains `timestamp`, `level`, `service`,
  `logger`, `message`, and `request_id`; request-completion records add `method`, `path`, and `status_code`.
  Request bodies, query values, and headers such as `X-API-Key` are intentionally excluded.
- Existing upstream and order-boundary `logger.error` calls remain in place; the logging change adds
  structure and cross-service linkage without adding speculative error sites.

## Phase 5 resilience extensions

- `POST /orders` accepts an optional `Idempotency-Key` header (1–255 characters). Order Service persists the
  key, canonical request identity, created order, and immutable creation-response snapshot. An exact replay
  returns the original confirmed `201` response even if the live order is later cancelled; reuse with any
  different payload returns `409`. Existing callers may omit the key.
- `PATCH /inventory/{productId}` accepts the same optional header for `quantityDelta` requests. Inventory
  persists the key, request identity, and successful response. An exact replay returns the original `200`
  response without applying the delta again; reuse for a different product or delta returns `409`.
- Order creation forwards `order-create:{caller_key}` to Inventory, while cancellation sends
  `order-cancel:{order_id}`. The separate namespaces prevent caller keys from colliding with deterministic
  cancellation keys and keep retries safe after ambiguous Inventory responses.
- Product and Inventory `GET` calls use at most three attempts with exponential backoff for transport errors
  and `5xx` responses. Inventory `PATCH` is single-attempt only.
- Successful Product and Inventory responses, including Inventory `PATCH` results, are validated with
  service-specific Pydantic models and must identify the requested product. Contract validation, identifier
  mismatches, and malformed Inventory `409` payloads surface from Order Service as `502 Bad Gateway`;
  recognized insufficient-inventory and idempotency conflicts retain their `409` semantics.

> **Revised after review.** This slice originally shipped as `POST /orders/{id}/cancel`. The Review phase
> flagged the verb in the path against [copilot-instructions.md](../../.github/copilot-instructions.md), and
> the endpoint was reshaped into `PATCH /orders/{id}` with a status body — mirroring the existing
> `PATCH /inventory/{productId}`. See [review-findings.md](review-findings.md).

## Endpoint: `PATCH /orders/{order_id}`

- **Request model:** `OrderStatusUpdate` — a single `status` field typed `Literal["CANCELLED"]`, so any
  other target state is rejected as `422` by Pydantic rather than by a hand-written `if` in the route.
  Widening the endpoint later is a one-line change to that `Literal`.
- **Response model:** reuses the existing `Order` response model — the shape doesn't change, only
  `status` transitions to `"CANCELLED"`. This does **not** violate the "own request/response model per
  operation" rule, since that rule targets input/output shape reuse across different resources, and
  cancellation returns the same `Order` resource it's mutating (same as `PATCH` returning the updated
  resource elsewhere in this repo).
- **Status codes:**
  - `200` — cancelled; body is the updated `Order` with `status: "CANCELLED"`.
  - `404` — no order with that id (existing `Order` lookup, same as `GET /orders/{id}`).
  - `409` — order is already `"CANCELLED"` (repeat-cancel is a conflict, not a validation error, matching
    this repo's existing 409 usage for "insufficient inventory").
  - `422` — `status` is absent or is not `"CANCELLED"`.
  - `502` — Inventory Service is unreachable/times out while restoring stock, matching this repo's existing
    upstream-failure mapping in `create_order`.

## Folder structure

No new files or packages. Extend the existing Order Service layout in place:

```
services/order_service/app/
  routes.py     # add PATCH /orders/{order_id}
  clients.py    # add InventoryClient.restore_inventory(product_id, quantity)
  models.py     # add OrderStatusUpdate; Order.status narrowed to a Literal
```

`clients.py` gets a new method rather than a new file because `restore_inventory` is the same PATCH
operation as the existing `reduce_inventory`, just adjusting the quantity upward instead of downward — one
private helper (`_adjust_quantity`) backs both public methods to avoid duplicating the HTTP/error-handling
logic.

## Decisions worth confirming

1. **Status transitions travel in a body, not a path segment** — `PATCH /orders/{id}` with
   `{"status": "CANCELLED"}` keeps the path free of verbs and leaves room for future transitions without
   adding another endpoint.
2. **`restore_inventory` reuses the same PATCH as `reduce_inventory`** via a shared private helper in
   `InventoryClient`, rather than a second inline `httpx` call — keeps clean-architecture intent from
   [backend-api-expert.agent.md](../../.github/agents/backend-api-expert.agent.md).
3. **Inventory adjustments are deltas, resolved server-side** — both flows send
   `PATCH /inventory/{productId} {"quantityDelta": ±n}` instead of reading the current quantity and writing
   back an absolute. Inventory Service applies the delta to its own stored value and returns `409` if that
   would drive stock below zero, so concurrent orders and cancellations can no longer overwrite each other
   (see [order-creation-sequence.md](order-creation-sequence.md)).
