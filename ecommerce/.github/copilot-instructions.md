# E-Commerce API — Project Guidelines

See [README.md](../README.md) for architecture overview and how to run each service.

## Code Style
- The target runtime is the latest stable Python 3 release. Type hints are required on every function
  signature and Pydantic model field.
- Each resource has its own FastAPI `APIRouter`, mounted in `app/main.py`.
- Request/response schemas are Pydantic models in `app/models.py`, with `Create`/`Update` input models kept
  separate from the response model.
- Business and validation logic belongs in small, reusable functions or repository classes — not inline in
  route handlers.

## REST Conventions
- Paths use plural resource nouns (`/products`, `/inventory`, `/orders`) and contain no verbs.
- Status codes: `200` (read/update ok), `201` (created — response carries the created resource), `204`
  (deleted — no body), `404` (resource not found), `409` (conflict — e.g. duplicate resource or insufficient
  inventory, with a JSON body whose `detail` field explains the conflict), `422` (validation error — handled
  by FastAPI/Pydantic).
- Product, inventory, and order resource endpoints require the `X-API-Key` header matching `API_KEY`.
  `/health` remains unauthenticated for compose, CI, and local readiness probes. The repository's
  `local-development-api-key` default is for local use only and must be overridden outside local development.

## Cross-Service Calls
- A service never imports another service's Python modules; cross-service communication goes over HTTP with
  `httpx`.
- Order Service calls to Product or Inventory carry an `httpx` timeout (e.g. 5s). Non-2xx responses and
  timeouts surface as `502 Bad Gateway` from the Order Service with a JSON error detail.
- Any `httpx.RequestError` (connection, DNS, timeout) or non-2xx response from a downstream service surfaces
  as `502 Bad Gateway` with a JSON `detail` describing the upstream failure.

## Validation
- Input validation relies on Pydantic `Field` constraints and `field_validator`, not manual `if` checks in
  routes.
- Validators shared across `Create`/`Update` models live in a shared base model.

## Testing
- Every endpoint has `pytest` tests using `fastapi.testclient.TestClient`, covering the happy path, a 404
  case, and a validation (422) case.
- In-memory storage is reset between tests by an `autouse` fixture.
- Each service uses a module-level dict or repository class for in-memory storage, exposed via a
  dependency-injected getter so tests can reset it.
