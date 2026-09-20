# Exercise 5 — SDLC Agents → Planning → Design → Coding → Testing → Review

**Goal:** drive one feature end-to-end through five SDLC phases, each handled by a purpose-scoped Copilot
agent, and land every phase's output as a committed artifact under `docs/sdlc/`.

Exercises 1–4 each produced *one* customization asset. This exercise is different: it's about **composition**
— chaining several narrow agents so each phase's written output becomes the next phase's input. The agents
don't call each other; the artifacts on disk are the handoff mechanism.

The three services already exist, so the feature carried through all five phases should be a *new* one rather
than a rebuild. Suggested vertical slice: **order cancellation** (`POST /orders/{id}/cancel` — restores
inventory, marks the order cancelled), which touches Order Service and Inventory Service and therefore
exercises the cross-service rules in [copilot-instructions.md](../.github/copilot-instructions.md).

## Step 1 — Create the phase agents

Four new agents in `.github/agents/`, alongside the existing `backend-api-expert`:

| File | Phase | Writes to |
| --- | --- | --- |
| `sdlc-planner.agent.md` | Planning | `docs/sdlc/user-stories.md` |
| `sdlc-designer.agent.md` | Design | `docs/sdlc/api-design.md`, `docs/sdlc/order-creation-sequence.md` |
| `backend-api-expert.agent.md` *(already exists)* | Coding | `services/**` |
| `sdlc-tester.agent.md` | Testing | `services/*/tests/**` |
| `sdlc-reviewer.agent.md` | Review | `docs/sdlc/review-findings.md` |

**Coding reuses the Exercise 3 agent** rather than adding a fifth — `backend-api-expert` already owns REST
design, clean architecture, validation, and logging/error handling, which is exactly the Coding phase's
remit. Creating an `sdlc-coder` would duplicate it and split the conventions across two files.

Frontmatter follows the shape already proven in
[backend-api-expert.agent.md](../.github/agents/backend-api-expert.agent.md) — a `description` plus a `tools`
array using this workspace's namespaced tool IDs:

```yaml
---
description: <one line, since this is what the agent picker shows>
tools: ['search/codebase', 'search', 'edit/editFiles', 'execute/runInTerminal', 'read/problems']
---
```

Per-agent tool scoping — this is the point of having separate agents at all:

- **Planner / Designer** — `edit/editFiles` is needed (they write markdown), but drop `execute/runInTerminal`;
  neither phase should be running commands.
- **Tester** — needs `execute/runInTerminal` (to actually run `pytest`) plus `execute/testFailure` and
  `read/problems`.
- **Reviewer** — **no `edit/editFiles` at all.** A review agent that can silently fix what it finds produces
  no review. It reports findings and leaves remediation to a separate, explicit turn.

Each agent body should reference [copilot-instructions.md](../.github/copilot-instructions.md) and state that
repo conventions win on conflict — same pattern as the Exercise 3 agent.

## Step 2 — Planning

Run `sdlc-planner` with the cancellation slice. Ask for user stories covering the three domains the spec
names — product management, inventory management, order processing.

The agent's instructions should require each story to carry:
- `As a <role>, I want <capability>, so that <outcome>` — one sentence, no compound stories.
- A stable ID (`US-01`, `US-02`, …) so later phases can cite it.
- Acceptance criteria in Given/When/Then form, including at least one failure path.
- An explicit HTTP status code per acceptance criterion, drawn from the repo's established set
  (`200`/`201`/`204`/`404`/`409`/`422`) — this is what makes the stories usable as design input rather than
  prose.

Output: `docs/sdlc/user-stories.md`.

## Step 3 — Design

Run `sdlc-designer` with `docs/sdlc/user-stories.md` attached. Three deliverables, per the spec:

1. **API design** — endpoint table (method, path, request model, response model, status codes, the `US-xx`
   it satisfies), plus the Pydantic model shapes. No implementation.
2. **Folder structure** — where cancellation code lands in the existing layout. Expect this to be "no new
   files, extend `routes.py`/`models.py`/`clients.py`"; an agent proposing a new top-level package is a
   signal it ignored the existing structure, which is worth catching in the lab.
3. **Sequence diagram for order creation** — Mermaid `sequenceDiagram` covering the documented workflow:
   validate product → check inventory → reduce inventory → create order → return confirmation, including
   the `502` upstream-failure branch and the non-atomic read-then-write gap already flagged in
   [routes.py](../services/order_service/app/routes.py).

Have the designer diagram **order creation** (as the spec asks) and then extend it with the cancellation
flow, so the diagram documents existing behavior and the new slice side by side.

## Step 4 — Coding

Switch to `backend-api-expert` with the design attached. Generate models, route handlers, and the
service/client layer for cancellation.

The Exercise 4 hook fires here — every `.py` edit triggers `ruff format`, `ruff check --fix`, and the owning
service's `pytest`, and the result surfaces as a `systemMessage`. This is the first phase where Exercises 4
and 5 visibly interact, and it's worth pausing on: the hook is agent-agnostic, so it gates *every* agent's
edits, not just the one it was built alongside.

## Step 5 — Testing

Run `sdlc-tester`. The spec asks for three categories, which map onto the repo's existing test conventions:

- **Unit tests** — happy path per endpoint, via `TestClient`.
- **Negative test cases** — `404` (unknown order), `409` (cancelling an already-cancelled order), `422`
  (malformed payload).
- **Inventory validation tests** — that cancellation restores the exact quantity, and that an Inventory
  Service failure during restore surfaces as `502` and leaves the order un-cancelled.

The tester agent must use the fake-client + `dependency_overrides` pattern already established in
[test_orders.py](../services/order_service/tests/test_orders.py) rather than inventing a mocking approach,
and must actually run `pytest -q` and report the count — a testing phase that only *writes* tests hasn't
validated anything.

## Step 6 — Review

Run `sdlc-reviewer` over the diff from Steps 4–5. Four review lenses, per the spec:

- Bugs.
- Improvements.
- REST API design conformance.
- Security concerns.

Require each finding to be written as `file:line — problem — why it matters — suggested fix`, and require an
explicit "no findings" statement per lens when a lens is clean. Without that, a review agent will pad the
list to look thorough.

Output: `docs/sdlc/review-findings.md`. Then triage in a normal chat turn — accept, defer, or reject each
finding — so the review is a decision record, not just generated text.

## Step 7 — Verify the chain held

The exercise succeeds only if the phases actually fed each other. Check:
- Every endpoint in `api-design.md` traces back to a `US-xx` in `user-stories.md`.
- Every endpoint in `api-design.md` exists in the implementation, with the status codes the design specified.
- Every acceptance criterion has a corresponding test.
- `pytest -q` is green in every service touched.

A quick way to confirm: attach all of `docs/sdlc/` and ask any agent to produce the traceability table
`US-xx → endpoint → test`. Gaps show up immediately as empty cells.

## Decisions worth confirming

1. **Artifacts are the handoff, not agent-to-agent calls** — each phase reads the previous phase's committed
   file. This keeps every phase independently re-runnable and reviewable, and it's what makes the chain
   visible in the repo afterward.
2. **Coding reuses `backend-api-expert`** — no `sdlc-coder` agent, to avoid two files owning the same
   conventions. Revisit only if the coding phase needs rules the Exercise 3 agent shouldn't apply to reviews.
3. **The reviewer has no edit tool** — deliberate. Review output is a findings list; remediation is a
   separate, explicit turn so nothing gets silently changed under the guise of "review".
4. **One vertical slice through all five phases** — order cancellation, rather than one unrelated exercise
   per phase. The handoffs are the actual lesson here, and they're only observable if the same feature moves
   through the whole chain.
5. **`docs/sdlc/` rather than per-phase folders** — flat and committed, matching how Exercises 2–4 shipped
   their deliverables, and it's the "SDLC agent outputs" item on the lab's deliverables list.
6. **Timebox risk** — 30 minutes across five phases is tight once four agent files are authored. If time is
   short, author the planner and reviewer agents only (the two phases with no existing coverage) and run
   Design/Coding/Testing as plain prompts against `backend-api-expert`.
