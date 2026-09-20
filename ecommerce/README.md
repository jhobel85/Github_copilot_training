# E-Commerce API

## Architecture
Three independent FastAPI services live under `services/`: `product_service`, `inventory_service`, `order_service`.
Each is runnable standalone (own `requirements.txt`, own `app/` package, own `tests/`). The Order Service calls
the other two over HTTP using `httpx`. An additional `mcp_server` exposes the services through MCP tools and a
read-only catalog resource for use by AI agents/assistants (e.g. VS Code's `.vscode/mcp.json`).

## Running a Service
From inside `services/<service_name>/`:
```
pip install -r requirements.txt
uvicorn app.main:app --reload --port <port>
pytest
```
Ports: product=8001, inventory=8002, order=8003.

## MCP Server
`services/mcp_server` wraps the three REST services as MCP tools (`list_products`, `find_product`,
`create_product`, `list_inventory`, `check_inventory`, `create_inventory`, `adjust_inventory`, `list_orders`,
`get_order`, `create_order`, `cancel_order`) so an MCP-capable client can browse products, check stock, and
place/cancel orders directly. It also exposes the read-only `products://catalog` resource as
`application/json`. Reading it loads the complete catalog in 100-item pages through the same authenticated
Product Service client used by the tools.

```
cd services/mcp_server
pip install -r requirements.txt
python -m app.main        # runs the server over stdio
pytest                     # integration tests boot the real product/inventory/order services and call the
                           # tools end-to-end over HTTP
```

By default the tools call `http://localhost:8001/8002/8003`; override with the `PRODUCT_SERVICE_URL`,
`INVENTORY_SERVICE_URL`, and `ORDER_SERVICE_URL` environment variables. The MCP client sends the API key
configured by `API_KEY`. It's registered for VS Code in [.vscode/mcp.json](.vscode/mcp.json).

Expected upstream failures are returned as typed MCP v2 protocol errors rather than generic execution
failures. Their structured `data` contains `type`, `service`, `detail`, and `status_code`. Clients can branch
on `upstream_not_found` for a missing resource, `upstream_unavailable` for connection failures and upstream
`5xx` responses, and `upstream_rejected` for other upstream `4xx` responses.

## Testing

- Unit/integration tests are per-service under `services/<service>/tests` (`pytest` from the service dir).
- A cross-service browser test lives in `tests/browser/`. It boots all three services as real uvicorn
  subprocesses on ports 8101-8103 (isolated temp databases, dedicated test API key) and drives each
  Swagger UI (`/docs`) in a Playwright Chromium browser the same way a human would: Authorize,
  Try it out, fill the form, Execute, then asserts the rendered response for 200/201, 404, 422 and
  409 cases plus the product -> inventory -> order inventory-delta invariants.
  Requires the dependency: `pip install -r requirements-dev.txt && python -m playwright install chromium`.
  It is excluded from default runs (registered as the `browser` mark), so CI/local runs need it explicitly:

```
python -m pytest -m browser            # headless (default)
BROWSER_HEADLESS=0 python -m pytest -m browser            # live visible Chromium window (on the test machine)
BROWSER_VIDEO=1 python -m pytest -m browser               # record a WebM to tests/browser/video/
BROWSER_SLOWMO=500 python -m pytest -m browser            # slow each Playwright action by 500ms
BROWSER_VIEW_PAUSE_SECONDS=120 python -m pytest -m browser   # keep the stack up 120s after the run
```

**Watching it from your own machine — zero manual steps.** When `cloudflared` is installed
(`curl -L -o ~/.local/bin/cloudflared
https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 &&
chmod +x ~/.local/bin/cloudflared`), every run starts temporary, account-less Cloudflare quick
tunnels for the three services and prints public `*.trycloudflare.com/docs` URLs in the pytest
output — open them in any browser to browse the live stack (read/write against the temporary
test data). Tunnels and services are always torn down when the session ends; if `cloudflared` is
absent or the machine is offline, the run degrades to local-only with a stderr notice.
Tunnels require **outbound port 7844 (UDP, or TCP as fallback)** which Cloudflare uses for its
edges — corporate egress proxies that block it (e.g. the "CONNECTIVITY PRE-CHECKS" showing
`QUIC connection failed` / `HTTP/2 connection is blocked`) need IT to allow that port, or the
suite must run on a machine without that restriction. The test itself only needs local
loopback, so it passes regardless.

## Authentication and pagination

Every `/products`, `/inventory`, and `/orders` endpoint requires `X-API-Key` matching the service's
`API_KEY` environment variable. `/health` remains unauthenticated. Local runs default to
`local-development-api-key`, which is also set explicitly in `docker-compose.yml` and `.vscode/mcp.json`;
override it in any non-local environment. The key is never logged.

The three collection endpoints accept `limit` (default `50`, range `1..100`) and `offset` (default `0`,
minimum `0`). Invalid values return `422`. Results are deterministic: products by id, inventory by product
id, and orders by creation time then id. MCP `list_products`, `list_inventory`, and `list_orders` expose the
same arguments and pass them through.

## Logging and request correlation

All three APIs emit one-line JSON logs with `timestamp`, `level`, `service`, `logger`, `message`, and
`request_id` fields. Request-completion records also include `method`, `path`, and `status_code`; headers,
query values, and request bodies are not logged.

Clients may send `X-Request-ID` on any request. The service returns the same value in the response; when the
header is absent, it generates and returns a UUID. Order Service forwards the active request ID on every
Product and Inventory request so logs from one order flow can be joined across services. Request IDs use
context-local state, so concurrent requests do not leak correlation values into one another.

Uvicorn lifecycle and access records use the same JSON stream without duplicate plaintext handlers. Access
logs omit query strings, and unexpected application failures retain the generic `500 Internal Server Error`
response while returning `X-Request-ID` and emitting a correlated structured error record.

## API Overview

### Product Service (`:8001`)
| Method | Path | Status codes |
|---|---|---|
| GET | `/products?limit=50&offset=0` | `200`, `401`, `422` |
| GET | `/products/{id}` | `200`, `401`, `404` |
| POST | `/products` | `201`, `401`, `422` |
| GET | `/health` | `200` |

### Inventory Service (`:8002`)
| Method | Path | Status codes |
|---|---|---|
| GET | `/inventory?limit=50&offset=0` | `200`, `401`, `422` |
| GET | `/inventory/{productId}` | `200`, `401`, `404` |
| POST | `/inventory` | `201`, `401`, `409` |
| PATCH | `/inventory/{productId}` | `200`, `401`, `404`, `409`, `422` |
| GET | `/health` | `200` |

`PATCH /inventory/{productId}` accepts either an absolute `quantity` or a `quantityDelta` (not both). A delta
is resolved server-side against the currently stored quantity, so concurrent adjustments can't overwrite one
another; a delta that would drive stock below zero returns `409`. For delta adjustments, an optional
`Idempotency-Key` header records the response persistently. Replaying the same key and request returns that
original response without applying the delta again; reusing the key for a different adjustment returns `409`.

### Order Service (`:8003`)
| Method | Path | Status codes |
|---|---|---|
| GET | `/orders?limit=50&offset=0` | `200`, `401`, `422` |
| GET | `/orders/{id}` | `200`, `401`, `404` |
| POST | `/orders` | `201`, `401`, `404`, `409`, `422`, `502` |
| PATCH | `/orders/{id}` | `200`, `401`, `404`, `409`, `422`, `502` |
| GET | `/health` | `200` |

`PATCH /orders/{id}` transitions an order's status via a body (`{"status": "CANCELLED"}`) rather than an
action path segment, and restores the order's quantity back to Inventory Service as an atomic delta.

`POST /orders` accepts an optional `Idempotency-Key` header. Order Service persists the canonical request
identity and an immutable snapshot of the creation response: an exact replay returns the original confirmed
response even if the live order is later cancelled, while reuse with a different payload returns `409`.
Inventory adjustments use separate `order-create:` and `order-cancel:` key namespaces, so caller-supplied
creation keys cannot collide with cancellation keys.

Order Service retries Product and Inventory `GET` requests at most three times with exponential backoff for
transport failures and `5xx` responses. Inventory `PATCH` requests are never automatically retried. Malformed
successful upstream payloads, including Inventory `PATCH` responses and product identifiers that do not match
the requested resource, are treated as `502 Bad Gateway`. Malformed Inventory conflict payloads are also
treated as `502`; recognized insufficient-inventory and idempotency conflicts remain `409`.

See [docs/sdlc/api-design.md](docs/sdlc/api-design.md) for full request/response schemas and design rationale.
