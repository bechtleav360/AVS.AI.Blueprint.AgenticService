# SessionsBus: register with the dispatch registry before opening the SSE stream

- **Date:** 2026-07-06
- **Issues:** [#45](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/issues/45) (register-before-connect), [#44](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/issues/44) (keepalive log noise) — both closed by this work
- **Milestone:** v0.7.0

## Problem

Sessions service **v0.4.0** gates the SSE job stream on an explicit agent registry
(`service-sessions` #27/#82). `GET /jobs/stream/sse` returns **403 (JSON)** unless the
agent has previously called `POST /agents/register`. `SessionsBus` connects straight to
the stream without registering, so after the v0.4.0 deploy all deployed agents fell into
an infinite 5-second reconnect loop:

```
httpx_sse._exceptions.SSEError: Expected response header Content-Type to contain
'text/event-stream', got 'application/json'
Reconnecting in 5 seconds...
```

The `SSEError` hides the real status/reason, which cost most of the diagnosis time.

A related papercut (#44): the service emits an SSE keepalive comment frame (`: keepalive`
with an `id:` and no `event:`/`data:`) every 30 s. `SessionsBus` dispatches it as a
default-type `message` event with empty data, which falls through to a
`WARNING - Unknown SSE event type: message` on every tick — one per keepalive, indefinitely.

## Server contract (verified against `service-sessions`)

`POST {base_url}/agents/register` — no `/api` prefix internally (the manual stopgap's `/api`
was the ingress path; relative to the configured `base_url` it is `/agents/register`, matching
the existing `SessionsApiClient` endpoints such as `/sessions/{id}/jobs/...`).

- **Auth:** service-wide `X-Api-Key` (same gate as `/jobs/*`). No session key.
- **Request body** (`AgentRegisterRequest`): `agent_id` (str, required), `agent_type` (str, required),
  `capabilities` (list[str], default `[]` = all job types — **this is the dispatch source of truth**,
  not the SSE query string), `version` (str, optional), `metadata` (dict, optional).
- **Response:** **201** on first (or post-expiry) registration; **200** when re-posting a still-live
  `agent_id` (heartbeat refresh that re-declares capabilities). Both are success.
- **Liveness:** registrations live in RAM and lapse after a heartbeat TTL (~60 s) unless refreshed by
  a re-register or by SSE keepalives. An open stream does not expire.
- **Graceful teardown:** `DELETE {base_url}/agents/{agent_id}` — idempotent, returns **204** whether or
  not the agent was registered.
- **Legacy servers** (< v0.4.0) have no `/agents/register` route → the call returns **404**.

## Design decisions

1. **Scope:** fix #45 and #44 together — both touch the SSE connect/consume path (`_connect_and_consume`).
2. **Registration lives in `SessionsApiClient`**, alongside `start_job`/`complete_job`/`cancel_job`. It
   already owns the persistent `httpx.AsyncClient` with the `X-Api-Key` header baked in, and is cleanly
   unit-testable.
3. **Register on the per-attempt path**, not in `on_startup`. Registering at the top of
   `_connect_and_consume()` satisfies "re-register before every reconnect attempt" *and* covers the very
   first connect (the SSE task's first iteration), so no separate `on_startup` register call is needed.
4. **Registration failure == connection failure.** A hard register failure raises and flows into the
   existing reconnect/backoff loop — no new control flow. This also preserves app-startup resilience:
   failures occur inside the background SSE task, never in `on_startup`.
5. **Graceful unregister on shutdown**, using the `DELETE` endpoint (best-effort).
6. **Fold in Brooks-Lint review findings.** A PR-review of the two touched files (2026-07-06, health
   84/100) surfaced pre-existing conditions worth fixing while we are in this code: a shared request
   helper in `SessionsApiClient`, a single dispatch seam in `SessionsBus`, extraction of the four error
   policies out of `_process_job_notification`, a typed `JobNotification` model, and a defined shutdown
   drain for in-flight job tasks. Detail in [Folded-in refactors](#folded-in-refactors-brooks-lint-review).
   These are separate commits within the PR so the registration change stays reviewable on its own.

## Components

### `SessionsApiClient._request(...)` (new, shared — folds in Suggestion #4)

Every existing method repeats the same preamble: the `if not self._client: raise ValueError("...not
initialized...")` guard, URL assembly, header assembly, `raise_for_status()`, `.json()`, and a log line.
Adding `register_agent`/`unregister_agent` would copy it a fifth and sixth time. Extract it once:

```python
async def _request(
    self,
    method: str,
    path: str,
    *,
    session_key: str | None = None,
    json: dict[str, Any] | None = None,
) -> httpx.Response:
    """Issue an authenticated request to the sessions service.

    Owns the client-initialised guard, URL assembly, and the optional X-Session-Key
    header. Returns the raw Response so callers decide how to treat status codes
    (register/unregister need to branch on 404 rather than always raise_for_status).
    """
```

- The four existing methods (`start_job`, `get_job_detail`, `complete_job`, `cancel_job`) migrate to
  `_request(...)` + `raise_for_status()` + `.json()`, preserving their current behaviour exactly.
- `_request` does **not** call `raise_for_status()` itself — registration needs to inspect 404/2xx
  before deciding — so status handling stays with each caller.

### `SessionsApiClient.register_agent(...)` (new)

```python
async def register_agent(
    self,
    agent_id: str,
    agent_type: str,
    capabilities: list[str],
    version: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Register the agent with the sessions dispatch registry (idempotent).

    Returns True when the server accepted the registration (200/201).
    Returns False when the server is a legacy (< v0.4.0) instance without the
    endpoint (404) — the caller may still open the stream. Raises on any other
    non-2xx so the reconnect loop backs off.
    """
```

Behaviour:

- `await self._request("POST", "/agents/register", json=payload)` with `payload = {agent_id, agent_type,
  capabilities}` (+ `version`/`metadata` only if provided). `X-Api-Key` is already a default header on the
  client; the guard lives in `_request`.
- **200 / 201** → log at INFO (include status), return `True`.
- **404** → log once at WARNING ("sessions service has no /agents/register; legacy < v0.4.0, proceeding
  without registration"), return `False`.
- **Any other non-2xx** → log status **and `response.text`** (satisfies "surface the 403 body"), then
  `response.raise_for_status()`.

### `SessionsApiClient.unregister_agent(...)` (new)

```python
async def unregister_agent(self, agent_id: str) -> None:
    """Best-effort graceful deregistration (idempotent DELETE). Never raises."""
```

- `await self._request("DELETE", f"/agents/{agent_id}")`.
- Swallow **all** exceptions (network error, 404 on legacy, closed client) — log at WARNING on failure,
  INFO on success. Shutdown must never fail because of this call.

### `SessionsBus` changes

**`_connect_and_consume()` — register before opening the stream:**

```python
async def _connect_and_consume(self) -> None:
    # Register (or refresh) before opening the stream. On a legacy server this
    # is a no-op (404 → False); on a hard failure it raises → reconnect backoff.
    await self._api_client.register_agent(
        agent_id=self._agent_id,
        agent_type=self._agent_type,
        capabilities=self._capabilities,
    )

    url = f"{self._base_url}/jobs/stream/sse"
    ...  # existing connect logic unchanged below
```

**Keepalive handling (#44)** in the event-dispatch branch — a default-type `message` frame with empty
data is a keepalive comment, not an event:

```python
elif sse.event == "heartbeat":
    logger.debug("SSE heartbeat received")

elif sse.event == "message" and not (sse.data or "").strip():
    logger.debug("SSE keepalive frame received")   # #44 — was WARNING

else:
    logger.warning("Unknown SSE event type: %s", sse.event)
```

Named events *with* a payload still reach the `Unknown SSE event type` WARNING. The `job_created`
branch parses `sse.data` into a `JobNotification` (see [Folded-in refactors](#folded-in-refactors-brooks-lint-review))
rather than a raw dict.

**403 diagnostics** — wrap the event iteration so a rejected stream surfaces its real status and body
instead of an opaque `SSEError`:

```python
async with aconnect_sse(client, "GET", url, params=params, headers=headers) as event_source:
    logger.info("SSE connection established")
    try:
        async for sse in event_source.aiter_sse():
            ...
    except SSEError:
        resp = event_source.response
        body = (await resp.aread()).decode(errors="replace")[:500]
        logger.error("SSE stream rejected: status=%d body=%s", resp.status_code, body)
        raise   # let the reconnect loop back off
```

**`on_shutdown()` — stop the stream, drain in-flight jobs, then unregister:**

```python
async def on_shutdown(self) -> None:
    self._shutdown_event.set()
    # cancel the SSE task (existing logic) ...
    await self._drain_inflight_jobs()          # folds in the shutdown-drain refactor
    if self._api_client and self._agent_id:
        await self._api_client.unregister_agent(self._agent_id)
```

The order is deliberate: setting `_shutdown_event` stops the consumer from accepting new jobs, we let
in-flight job tasks finish (bounded by a drain timeout), and only then unregister — so we never pull the
registration out from under a job that is still reporting results. See
[Folded-in refactors](#folded-in-refactors-brooks-lint-review) for the task-tracking detail.

Teardown order makes the client available here: `SessionsBus` is registered as a *lifecycle component*
(torn down first, `app_builder.py` line ~348), whereas `SessionsApiClient` is a *service* (torn down
later, line ~392). The client's `httpx.AsyncClient` is therefore still open when `on_shutdown` runs.

## Folded-in refactors (Brooks-Lint review)

From the 2026-07-06 PR review of the two touched files (health 84/100). Each is a **separate commit**
within the PR, sequenced before the registration change where it de-risks it, so the core fix stays a
small, self-contained diff.

1. **`SessionsApiClient._request(...)` shared helper** — *Suggestion #4, Knowledge Duplication.* Extract
   the client guard + URL/header assembly repeated across the four existing methods; the four migrate to
   it with no behaviour change, and `register_agent`/`unregister_agent` build on it instead of copying the
   preamble a fifth and sixth time. Do this **first** so the new methods land clean.

2. **Single dispatch seam in `_process_job_notification`** — *Warning, Knowledge Duplication.* The happy
   path dispatches via `self._dispatch_cloud_event(event, context)` (`sessions_bus.py:255`); the 403-retry
   path bypasses the mixin and calls `EventProcessingService.process_event` directly (`:298-299`),
   silently dropping the mixin's result/`no_handler_found` handling. Route the retry through
   `_dispatch_cloud_event` too, so there is one dispatch path.

3. **Extract the four error policies** — *Warning, Cognitive Overload.* `_process_job_notification`
   (`:219-310`, ~80 lines) carries four recovery branches; the 403 branch raises inside an `except`, a
   control-flow quirk the tests document with multi-paragraph docstrings (`test_sessions_bus.py:260-299`).
   Extract `_cancel_invalid_job`, `_retry_with_fresh_key`, etc.; leave `_process_job_notification` a thin
   dispatcher. Combine with refactor #2 (same branch).

4. **`JobNotification` value object** — *Warning, Primitive Obsession / Domain Model Distortion.* The
   notification is threaded as `dict[str, Any]` and read inconsistently (`job_data["session_id"]` raises;
   `job_data.get("job_id")` is silently `None`). Add a small pydantic `JobNotification` (fields:
   `session_id: UUID`, `job_id: UUID`, `job_type: str`, `created_at`, `data`) parsed **once** in
   `_connect_and_consume`'s `job_created` branch; pass the typed object to `_handle_job_notification` /
   `_process_job_notification` / `_convert_to_cloud_event`. A malformed notification becomes an
   `InvalidEventError` at the boundary instead of a `KeyError` deep in processing.

5. **Shutdown drain for in-flight job tasks** — *robustness note from the review.* Jobs are launched
   fire-and-forget via `asyncio.create_task(...)` (`sessions_bus.py:187`) and today are orphaned on
   shutdown. Track them in a set (add on create, discard on done via callback); `on_shutdown` awaits them
   with a bounded timeout **before** unregistering (see the `on_shutdown` sketch above). The drain timeout
   reuses the existing `job_timeout_seconds` config (already loaded) rather than adding a new knob; tasks
   still running after it are cancelled so shutdown cannot hang.

**Guard:** if refactors #2–#5 make the diff hard to review as one PR, split #4 (JobNotification) into a
follow-up — it is the largest and is independent of the registration gate. #1–#3 and #5 should ship with
the fix.

## Error-handling semantics

| Event | Outcome |
|---|---|
| register 200 / 201 | proceed to open stream |
| register 404 | log "legacy server", proceed to open stream |
| register 4xx / 5xx / network error | log status + body, raise → reconnect backoff, retry next cycle |
| stream opens then drops | existing backoff → next cycle re-registers |
| SSE stream rejected (non-`text/event-stream`) | log real status + body, raise → backoff |
| malformed `job_created` payload | `InvalidEventError` at the SSE boundary → job cancelled, stream continues |
| keepalive `message` frame, empty data | DEBUG log, ignored (#44) |
| shutdown | stop stream → drain in-flight jobs (bounded) → best-effort `DELETE` unregister |

## Configuration

No new required config. `base_url`, `agent_id`, `agent_type`, `capabilities`, `api_key` are all already
loaded by `SessionsBus.on_startup`. `version`/`metadata` are intentionally **not** plumbed through
(YAGNI) — they can be added later without changing the method signatures (both are optional kwargs).

## Testing

**Unit — `SessionsApiClient`** (extend `tests/unit/agents/services/sessions/test_api_client.py`):
- `register_agent` 201 → returns `True`, POSTs to `/agents/register` with the expected body.
- `register_agent` 200 → returns `True` (heartbeat refresh).
- `register_agent` 404 → returns `False`, does **not** raise, logs the legacy warning.
- `register_agent` 500 → raises `HTTPStatusError`, response body appears in the log.
- `register_agent` uninitialised client → `ValueError` (guard now lives in `_request`).
- `unregister_agent` 204 → no raise; network error → swallowed (no raise), logged at WARNING.
- **Refactor #1:** existing `start_job`/`get_job_detail`/`complete_job`/`cancel_job` tests must stay green
  unchanged after the migration to `_request` (behaviour-preserving — this is the regression guard).

**Unit — `SessionsBus`** (`tests/unit/agents/io/api/eventing/test_sessions_bus.py`):
- `_connect_and_consume` calls `register_agent` **before** `aconnect_sse` (patch both; assert order).
- `register_agent` raising propagates out of `_connect_and_consume` (so `_consume_sse_stream` backs off).
- `on_shutdown` calls `unregister_agent(agent_id)` once, after task cancellation + drain, and does not raise if it fails.
- A `message` SSE frame with empty data logs at DEBUG and is **not** counted as an unknown event (#44).
- A named unknown event with a payload still logs the WARNING.
- **Refactor #2:** the 403-retry path invokes `_dispatch_cloud_event` (not `EventProcessingService.process_event`
  directly) — update `test_403_invalidates_cache_and_retries` accordingly.
- **Refactor #4:** a malformed `job_created` payload raises `InvalidEventError` at the boundary and the
  stream keeps consuming (one bad job does not drop the connection).
- **Refactor #5:** `on_shutdown` awaits an in-flight job task before unregistering; a job exceeding the
  drain timeout does not hang shutdown.

**Integration** (`tests/integration/test_sessions_startup_resilience.py`):
- Existing `test_app_starts_when_sessions_service_unreachable` must still pass unchanged — a register
  failure happens inside the background SSE task and must not block `on_startup`/lifespan completion.

## Docs

- `CHANGELOG.md`: entry under **v0.7.0** — "SessionsBus now registers with the sessions dispatch registry
  before opening the SSE stream (fixes 403 gate on sessions v0.4.0); keepalive frames no longer logged as
  unknown events. Closes #45, #44."
- `docs/concepts/event-processing.md`: add a note that SessionsBus registers (and re-registers on every
  reconnect) before streaming, and unregisters on graceful shutdown.

## Out of scope

- Feeding registration status into `SessionsServiceHealthChecker` (health already tracks REST reachability
  + SSE heartbeat; registration failures surface via the reconnect-loop logs).
- Any change to the SSE query-string params (`agent_type`/`capabilities`) — accepted but ignored by
  v0.4.0; left as-is for backward compatibility with older servers.
