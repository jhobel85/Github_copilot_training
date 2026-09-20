# Exercise 6 — GitHub Copilot CLI

**Goal:** run the same kinds of tasks Exercises 1–5 did through editor chat/agents, from the terminal instead,
against this repo's real gaps — then capture a short discussion note on when the CLI beats the editor.

## Step 0 — Install & authenticate

Prefer the standalone agentic CLI (`copilot`), since several of the exercise's example tasks (generate a
model, generate tests, generate a Dockerfile) need to read and write repo files, not just suggest a shell
command:

```
npm install -g @github/copilot
copilot --version
copilot          # from the repo root; run /login if not already authenticated
```

**Fallback:** if only the older `gh` extension is available in the lab environment
(`gh extension install github/gh-copilot`), it only exposes `gh copilot suggest` (shell command suggestions)
and `gh copilot explain` (explain a shell command) — no file generation. In that case, scope down to the
"explain an existing source file" task (piping a file through `explain`) and note the other four tasks as
"not reachable with this tool," which is itself a useful discussion point for Step 6.

## Step 1 — Task: explain an existing source file

Run against the most non-trivial file in the repo — `services/order_service/app/routes.py` (it now has both
`create_order` and `cancel_order`, each with multi-branch upstream error handling):

```
copilot explain services/order_service/app/routes.py
```

Capture the explanation output verbatim (paste into the deliverable, see Step 6) — no file changes here.

## Step 2 — Task: generate unit tests (real gap, not a demo)

`services/product_service/tests/test_products.py` has a `not_blank` validator in
[models.py](../services/product_service/app/models.py) (rejects whitespace-only `name`/`category`) that is
never actually exercised by a test — a genuine, currently-missing case. Ask the CLI to add it:

```
copilot -p "Add a pytest case to services/product_service/tests/test_products.py that asserts POST /products
with a whitespace-only name returns 422, following the existing sample_payload() pattern in that file."
```

Then run `pytest -q` in `services/product_service` and confirm the new test is collected and passes, same
verification discipline as every prior exercise.

## Step 3 — Task: generate a Product model (comparative demo, not a rewrite)

The real `Product` model already exists (Exercise 1) and should not be regenerated/overwritten. Use this task
to compare CLI output against the existing hand/agent-reviewed model instead:

```
copilot -p "Generate a Pydantic model for a Product with id, name, category, price, description fields,
matching typical FastAPI conventions" > docs/cli-demo/product-model-scratch.py
```

Diff the scratch file against [models.py](../services/product_service/app/models.py) mentally (validators,
`Field` constraints, `Create`/`Update` split), note the differences in the deliverable, then delete the
scratch file — nothing from this step is merged into `product_service`.

## Step 4 — Task: generate a Dockerfile (real gap — none exist yet)

None of the three services have a `Dockerfile` today. Generate one per service, since all three are
independently runnable FastAPI apps with their own `requirements.txt`:

```
copilot -p "Generate a Dockerfile for services/product_service: Python 3.12-slim base, install
requirements.txt, run uvicorn app.main:app on port 8001, following the same pattern for
inventory_service (8002) and order_service (8003)."
```

Expected output: `services/{product_service,inventory_service,order_service}/Dockerfile`, each installing
only that service's own `requirements.txt` and exposing its own port from the [README](../README.md) table —
no shared base image or compose file unless the CLI is explicitly asked for one (out of scope for this
exercise).

## Step 5 — Task: create a database schema (design artifact only)

All three services currently use in-memory storage (`storage.py` repository classes) — there is no real
database to migrate. Treat this as a documentation artifact showing what a relational schema would look like
if the in-memory stores were ever backed by one, explicitly not wired into the app:

```
copilot -p "Generate a SQL DDL schema (docs/database-schema.sql) for three tables — products, inventory,
orders — matching the fields in services/product_service/app/models.py,
services/inventory_service/app/models.py, and services/order_service/app/models.py, with inventory.productId
and orders.productId as foreign keys to products.id."
```

Output: `docs/database-schema.sql`, headed by a one-line comment noting it is illustrative only and not
consumed by any service.

## Step 6 — Capture usage + discussion

Add `docs/cli-usage-notes.md` recording, for each task above: the exact command run, a one-line summary of
what it produced, and how long it took to get an accepted result. Close with the discussion the spec asks
for — answer concretely from what changed hands in this exercise, not in the abstract:

- **Which tasks were faster in the CLI than editor chat, and why** — likely candidates: single-file,
  well-scoped generation (Dockerfile, schema, one test) where there's no multi-turn back-and-forth needed.
- **Which tasks would have been worse in the CLI** — anything needing the broader repo context a custom
  agent already holds (e.g. Exercise 3's Order Service, which needed cross-service design decisions) or
  needing an editor diff view to review before accepting (Exercise 4/5's larger multi-file changes).
- **Where the CLI fits day-to-day** — quick, scriptable, one-shot tasks and CI/terminal-adjacent workflows
  (e.g. this could plausibly *replace* a hand-written Dockerfile-generation step in a scaffolding script);
  editor chat/agents remain better for anything needing sustained context across a session (SDLC agents,
  hooks) or a visual diff before applying.

## Decisions worth confirming

1. **Scratch work isn't merged.** Step 3's model-generation output is discarded after comparison, not written
   into `product_service` — the real model was already built and reviewed in Exercise 1; regenerating it
   would silently overwrite reviewed work for no reason.
2. **Dockerfiles are a real, new deliverable**, not a demo-and-discard — the repo genuinely has none, so this
   is a legitimate place for the CLI's output to land in the codebase.
3. **The database schema is documentation, not a migration** — none of the three services touch a real
   database today (`storage.py` is in-memory), so `docs/database-schema.sql` stays illustrative; actually
   wiring a database is out of scope for this exercise.
4. **New test lands in the real suite, not a scratch file** — unlike the model task, the whitespace-name test
   is a genuine, previously-missing gap, so it's added directly to `test_products.py` and must pass under
   `pytest -q` like any other change in this repo.
5. **Fallback to `gh copilot` degrades the exercise, not the plan** — if only the shell-suggestion tool is
   available, fewer tasks are reachable, but that itself becomes a valid, worth-reporting discussion point
   in Step 6 rather than a blocker.
