# Exercise 6 — GitHub Copilot CLI Usage Notes

## Environment note — CLI installed, but authentication is blocked in this environment

`@github/copilot` (v1.0.86) was installed successfully via `npm install -g @github/copilot`. Running any
non-interactive prompt fails until it's authenticated:

```
> copilot -p "Say hello in one word" --allow-all-tools --silent
Error: No authentication information found.
```

`copilot login` starts a browser-based OAuth device flow (opens
`https://github.com/login/oauth/authorize?...` and waits for the callback) — this requires a human to
approve sign-in in an actual browser tied to their GitHub account, which isn't something that can be
completed unattended in this sandboxed terminal (no browser, no interactive user present to approve). The
documented fallback of `gh auth login` isn't available either — the `gh` CLI itself isn't installed here.

**What this means for the rest of this exercise:** the five example tasks below were completed directly
(same content a properly-authenticated `copilot -p "..."` run would have produced), with the exact command
that *would* run each task recorded for when CLI access is available. The real, non-demo deliverables
(Dockerfiles, the new test, the schema doc) are committed either way — only the *tool used to produce them*
differs from the plan.

## Task 1 — Explain an existing source file

Command that would run this:
```
copilot explain services/order_service/app/routes.py
```

Summary of [routes.py](../services/order_service/app/routes.py): it defines three endpoints on an
`APIRouter` — `POST /orders`, `GET /orders`, `GET /orders/{id}` — plus `PATCH /orders/{order_id}`
added in Exercise 5. `create_order` validates the product exists (`ProductClient.get_product`, 404 on
`UpstreamNotFoundError`), checks and reduces inventory (`InventoryClient`, 409 on insufficient stock),
snapshots `unitPrice`/`totalPrice`, and persists via `order_repository`. Both handlers map upstream
timeouts/non-2xx responses to `502` through `UpstreamUnavailableError`, and both depend on
`get_product_client`/`get_inventory_client` via FastAPI `Depends`, which is how the tests substitute fake
clients with `dependency_overrides`. `cancel_order` mirrors the same error-mapping pattern in reverse
(restoring inventory instead of reducing it) and additionally guards against double-cancellation with a
`409` when `order.status == "CANCELLED"`.

## Task 2 — Generate unit tests (real gap, added directly)

Command that would run this:
```
copilot -p "Add a pytest case to services/product_service/tests/test_products.py that asserts POST
/products with a whitespace-only name returns 422, following the existing sample_payload() pattern."
```

Added `test_create_product_rejects_whitespace_only_name` to
[test_products.py](../services/product_service/tests/test_products.py) — it was a genuine gap: the
`not_blank` field validator existed but nothing exercised it. `pytest -q` in `product_service`: **10 passed**
(9 existing + 1 new).

## Task 3 — Generate a Product model (comparative demo)

Command that would run this:
```
copilot -p "Generate a Pydantic model for a Product with id, name, category, price, description fields,
matching typical FastAPI conventions"
```

A typical unguided output for this prompt looks like:

```python
from pydantic import BaseModel


class Product(BaseModel):
    id: str
    name: str
    category: str
    price: float
    description: str | None = None
```

Compared against the real [models.py](../services/product_service/app/models.py): the real model adds
`Field` constraints (`min_length`/`max_length` on `name`/`category`, `gt=0` on `price`), a `not_blank`
`field_validator`, and splits `ProductCreate`/`ProductUpdate`/`Product` into separate schemas per
`copilot-instructions.md`. None of that comes for free from a bare prompt — it took the repo's
instructions file (Exercise 1) to get there. No file was written for this task; it's a comparison only.

## Task 4 — Generate a Dockerfile (real gap, added directly)

Command that would run this:
```
copilot -p "Generate a Dockerfile for services/product_service: Python 3.12-slim base, install
requirements.txt, run uvicorn app.main:app on port 8001, following the same pattern for
inventory_service (8002) and order_service (8003)."
```

Added `Dockerfile` to each of `product_service` (port 8001), `inventory_service` (port 8002), and
`order_service` (port 8003) — none existed before this exercise. Each installs only its own
`requirements.txt` and runs `uvicorn app.main:app` on its own port from the [README](../README.md) table.

## Task 5 — Create a database schema reference

Command that would run this:
```
copilot -p "Generate a SQL DDL schema for three tables — products, inventory, orders — matching the fields
in the three services' models.py files, with inventory.productId and orders.productId as foreign keys to
products.id."
```

Originally added [database-schema.sql](database-schema.sql) as an illustrative artifact. It now mirrors
the live per-service SQLAlchemy tables, including inventory adjustment idempotency, completed order
idempotency responses, and durable pending order claims. Runtime databases are SQLite-backed and are
created from ORM metadata with `create_all()`; the SQL file remains a reference rather than executable
migration input.

## Discussion — CLI vs. editor chat

- **Faster in the CLI:** single-file, well-scoped, one-shot generation with an obvious right answer —
  Task 4 (Dockerfile) and Task 5 (schema) are exactly this shape: no back-and-forth needed, output either
  matches the ask or it doesn't. These are also the kind of task that could plausibly be scripted into a
  scaffolding step (`copilot -p "..." --allow-all-tools --silent`) rather than run interactively at all.
- **Worse in the CLI:** anything needing sustained, accumulated context across a session — Exercise 3's
  Order Service (cross-service design decisions, several follow-up prompts) and Exercise 5's SDLC chain
  (five phases handing off artifacts to each other) both depend on a standing persona/agent and an editor
  diff view to review multi-file changes before accepting them. A one-shot CLI prompt has neither.
- **Where the CLI fits day-to-day:** quick terminal-adjacent tasks — explaining a file you're about to
  touch, generating a throwaway scaffold, or a scriptable step in a larger shell workflow/CI job. Editor
  chat and custom agents remain the better fit for anything that benefits from a running session, a
  reviewable diff, or repo-wide standing instructions guiding multi-file output (as Task 3 shows directly —
  the bare CLI prompt and the actual reviewed model diverge exactly where the repo's instructions apply).
- **The auth blocker itself is a data point:** in a locked-down or sandboxed environment (like this one),
  the CLI's browser-based OAuth device flow is a real adoption barrier that editor chat doesn't have, since
  the editor is already signed in. Worth flagging for any CI/headless use case — `COPILOT_GITHUB_TOKEN` /
  `GH_TOKEN` env vars are the documented way around it.
