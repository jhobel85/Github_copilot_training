# Exercise 2 — Prompt File → Inventory Service

**Goal:** a reusable API-generation prompt file, then use it to produce `services/inventory_service`
matching the Product Service structure.

## Step 1 — Create the prompt file

`.github/prompts/generate-api-service.prompt.md` (workspace-scoped so it ships as a lab deliverable).

Frontmatter:

```yaml
---
mode: agent
description: Scaffold a FastAPI resource service with validation, error handling, and tests.
---
```

Body covers the four spec bullets, parameterized by `${input:serviceName}` / `${input:resourceName}` so it
is genuinely reusable:

- **Generate REST endpoints** — `APIRouter` per resource, plural nouns, mounted in `app/main.py`, plus `/health`.
- **Add input validation** — Pydantic `Field` constraints + `field_validator`, shared base model across
  `Create`/`Update`.
- **Handle errors consistently** — `HTTPException` with `404` / `409`, JSON `detail` body.
- **Generate unit tests** — `TestClient`, happy path + 404 + 422, `autouse` reset fixture.

It intentionally does *not* restate repo-wide rules already in
[copilot-instructions.md](../.github/copilot-instructions.md) — that contrast is the point of Exercise 2
vs Exercise 1.

## Step 2 — Run the prompt for Inventory Service

Invoke with `serviceName=inventory_service`, `resourceName=inventory`.

## Step 3 — Expected output

```
services/inventory_service/
  requirements.txt          fastapi, uvicorn, pydantic, httpx, pytest
  app/__init__.py
  app/main.py               FastAPI app + router + /health
  app/models.py             InventoryBase / InventoryCreate / InventoryUpdate / InventoryItem
  app/routes.py             4 endpoints
  app/storage.py            InventoryRepository (in-memory dict, .clear() for tests)
  tests/__init__.py
  tests/test_inventory.py
```

Endpoints (per spec, keyed by `productId` not a surrogate id):

| Method | Path | Codes |
|---|---|---|
| GET | `/inventory` | 200 |
| GET | `/inventory/{productId}` | 200, 404 |
| POST | `/inventory` | 201, 409 (productId already tracked), 422 |
| PATCH | `/inventory/{productId}` | 200, 404, 422 |

Fields: `productId: str`, `quantity: int = Field(ge=0)`, `warehouse: str = Field(min_length=1)`,
`lastUpdated: datetime` (server-set on write, not client-supplied). `InventoryUpdate` has all-optional
fields since `PATCH` is partial.

## Step 4 — Verify

`pip install -r requirements.txt` then `pytest`, and run on port 8002 per the [README](../README.md).

## Decisions worth confirming

1. **`lastUpdated` is server-owned** — clients cannot set it; every write stamps `datetime.now(UTC)`.
2. **`PATCH` semantics** — partial update via `model_dump(exclude_unset=True)`, not full replacement.
3. **No cross-service product check** — Inventory Service stays standalone; validating that the product
   exists is the Order Service's job (Exercise 3).
