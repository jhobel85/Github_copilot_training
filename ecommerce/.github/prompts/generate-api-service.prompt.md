---
agent: agent
description: Scaffold a FastAPI resource service with validation, error handling, and tests.
---

Scaffold a new standalone FastAPI service at `services/${input:serviceName}/` for the
`${input:resourceName}` resource, following this project's conventions
(see [copilot-instructions.md](../copilot-instructions.md)). If `services/${input:serviceName}/`
already exists, stop and report the conflict to the user instead of overwriting files.

If the resource fields are not specified by the user, assume a minimal schema with
`id: str` (server-generated UUID) and `name: str` (required, 1-100 chars) without prompting, and
document this assumption in a comment at the top of `app/models.py`.

## Generate REST endpoints
- Create `app/main.py`, `app/models.py`, `app/routes.py`, `app/storage.py`, `app/__init__.py`,
  `tests/__init__.py`, `tests/test_${input:resourceName}.py`, and `requirements.txt`.
- Use a FastAPI `APIRouter` for the resource, mounted in `app/main.py`, plus a `/health` route.
- Use plural resource nouns for paths and no verbs. Derive the plural path segment by appending
  "s" to `${input:resourceName}`; if the user provides an explicit plural, use that instead.
- Default to these endpoints unless the resource spec says otherwise: `GET /{resources}` (list),
  `GET /{resources}/{id}`, `POST /{resources}`, `PUT /{resources}/{id}`, `DELETE /{resources}/{id}`.
- Back the service with an in-memory repository class exposing a `.clear()` method for test resets.
- Pin `fastapi>=0.110`, `pydantic>=2.5`, `pytest`, and `httpx` in requirements.txt. Use Pydantic v2
  APIs throughout.

## Add input validation
- Define Pydantic request/response models in `app/models.py` with a shared base model holding
  `Field` constraints and `field_validator`s reused by the `Create` and `Update` input models.
- Keep the response model separate from the input models.

## Handle errors consistently
- Raise `HTTPException` with `404` when a resource is not found, and `409` for conflicts (e.g.
  duplicate identifiers or business-rule violations), with a JSON body whose `detail` field explains
  the problem.
- Let FastAPI/Pydantic produce `422` for validation errors.
- Use server-generated string UUIDs for resource ids; reject client-supplied ids on POST. Return
  `409` only when a uniqueness constraint on a business field (not the id) is violated.

## Generate unit tests
- Use `fastapi.testclient.TestClient` in `tests/test_${input:resourceName}.py`.
- For each endpoint, cover the happy path. Additionally, add a `404` test for endpoints that take
  an `{id}` path parameter, and a `422` test for endpoints that accept a request body.
- Reset the in-memory repository between tests with an `autouse` pytest fixture.
