# FastAPI: working defaults

Defaults for FastAPI services — override with reason, local conventions win
(see the framing in `python-rules.md`, which this file assumes and extends).
Check the installed FastAPI/Pydantic versions before writing model code —
Pydantic v1 vs v2 changes idioms (`.dict()` vs `.model_dump()`, config style).

## The async contract (rule zero)

Decide per endpoint, on purpose:
- `async def` **only if everything inside is non-blocking** (async DB driver,
  httpx.AsyncClient, pure CPU-light logic). One blocking call — `requests`,
  `time.sleep`, sync driver, heavy CPU — freezes the entire event loop for all
  clients. This is the most common self-inflicted FastAPI wound.
- Plain `def` endpoints run in a threadpool and may block safely. When in doubt,
  or wrapping legacy sync code: plain `def` is the honest choice.
- CPU-heavy work belongs in neither — background worker/process, not the request
  path.

## Contracts: Pydantic at every door

- **Request bodies and responses are Pydantic models, never raw `dict`.** A
  `payload: dict` parameter silently accepts anything and validates nothing —
  the framework's main gift, refused. Models give you validation, docs, and a
  place to put constraints (`Field(gt=0)`, enums for closed sets).
- Set `response_model` (or return the model): it filters what leaks out —
  the difference between "returns the user" and "returns the password hash" is
  one forgotten field.
- Let 422s do their job: validation failures name the field and reason in the
  response body — read it when debugging instead of staring at the model.
- Errors are `HTTPException` with the right status and a useful `detail`;
  business-rule failures are 4xx with explanation, not 500s from uncaught
  exceptions, and not `{"ok": false}` with a 200.

## State, wiring, config

- **Shared resources go through dependencies (`Depends`)**, not module globals:
  DB sessions, clients, current user. Dependencies are swappable in tests
  (`dependency_overrides`) — module globals aren't; that's the whole argument.
- Remember the worker model: with multiple uvicorn/gunicorn workers, every
  module-level cache/counter exists once *per worker*. Anything that must be
  shared and consistent lives outside the process (Redis, DB). A cache that
  "randomly" misses under load is per-worker state.
- Any cache gets a TTL/invalidation story the day it's added (see
  `optimization.md`) — a cache without one is stale data on a schedule.
- Config and secrets via settings (pydantic-settings / env vars), never
  hardcoded (see `robustness.md`). Startup/shutdown via lifespan, so the app
  fails fast when mandatory config is missing.
- Structure by feature with routers (`APIRouter`), schemas/services/routes
  separated once the app outgrows one file; keep handlers thin — logic in plain
  testable functions, endpoint = parse, call, respond.

## Verification default

Every endpoint gets `TestClient`/httpx tests: the happy path, at least one
validation failure (assert the 422 and its message), and the feared case for that
endpoint (unauthorized, missing resource, duplicate submit — see `testing.md`).
Timeouts on all outbound calls; retries only on idempotent operations
(`robustness.md`). Then run the service and hit it with one real request —
TestClient passing and the server actually starting are different facts.
