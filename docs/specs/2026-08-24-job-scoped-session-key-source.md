# Spec: Add a job-scoped `"job"` source to `SessionKeyProvider`

**Issue:** bechtleav360/AVS.AI.Blueprint.AgenticService#76
**Depends on (server contract):** bechtleav360/avs.ai.idac.service-sessions#194

## Goal

Give `SessionKeyProvider` a working source for consumers whose session keys are generated fresh
per session and actually validated (encryption enforced) — the current `env`/`config` sources
only support one static key for every session, which cannot work for that case.

## Why now

Live-reproduced on `agents-document-analyser` against `avs.ai.idac.service-sessions`
(bechtleav360/avs.ai.project.pida#385): a job is dispatched and received correctly over SSE, then
`_process_job_notification` crashes immediately —

```
ValueError: Environment variable SESSION_KEY not set
  File "blueprint/agents/services/sessions/key_provider.py", line 138, in _get_from_env
```

`env` (the default) and `config` both assume one static key shared by every session — wrong by
construction once a consumer's sessions service issues (and validates) a distinct key per
session, which `avs.ai.idac.service-sessions` does whenever its encryption policy is at its
default (`storage.encryption_enabled=true`). `vault` raises `NotImplementedError`. `remote`
(`_get_from_remote`, fetch by `session_id`) has no matching server endpoint on
`avs.ai.idac.service-sessions` today, and building one that returns *any* session's key by id
alone would sit awkwardly next to that service's own "zero-knowledge encrypted sessions" framing.

## Root cause / gap

The class docstring already gestures at the right shape — "Per-session keys passed via context
(Phase 3)" — but it was never implemented: `get_session_key`'s branch list is only
`env`/`config`/`vault`/`remote`, and the docstring's `Options:` line (`env, vault, context`) has
also drifted from the actual code (missing `config` and `remote`, listing unimplemented
`context`). Sessions-side, nothing currently carries a session key anywhere the agent could read
it — not on the SSE notification, not anywhere else.

## Design

**New source: `"job"`.** Fetches the key from the job-scoped endpoint specified in
bechtleav360/avs.ai.idac.service-sessions#194 (`GET /internal/jobs/{job_id}/session-key`,
`X-Api-Key` auth) rather than adding a field to the broadcast/notification payload — see that
spec's "Why not put the key on the existing broadcast" section for the reasoning (this framework
is one of potentially several consumers of that service; the fetch-by-job-id shape is the
contract being proposed there, not something this repo should quietly assume by adding fields to
its own `JobNotification` model).

```python
# key_provider.py
async def get_session_key(self, session_id: UUID | None = None, job_id: UUID | None = None) -> str:
    ...
    if self._source == "job":
        session_key = await self._get_from_job(job_id)
    ...

async def _get_from_job(self, job_id: UUID | None) -> str:
    if not job_id:
        raise ValueError("job_id required for 'job' source")
    if not self._remote_url:
        raise ValueError("sessions_service.session_key_remote_url not configured")
    url = f"{self._remote_url}/internal/jobs/{job_id}/session-key"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, headers={"X-Api-Key": self._api_key})
        response.raise_for_status()
        return response.json()["session_key"]
```

- `job_id` is a new optional parameter on `get_session_key`, threaded through from the three call
  sites in `sessions_bus.py` (lines 377, 421, 445) — all three already have `job_id` in scope
  from the notification they're handling.
- **Caching is unchanged.** The existing cache keys by `session_id`, not by source — a `"job"`
  fetch populates the same `TTLCache` under `str(session_id)`, so a second job in the same
  session hits the cache without needing its `job_id` at all. Only the cache-miss path needs
  `job_id`.
- Reuses the existing `session_key_remote_url` / `api_key` config fields (already present for
  `remote`) rather than adding new ones — same shape, different path suffix.
- Fix the docstring's `Options:` line to list the actual implemented sources
  (`env, config, vault, remote, job`) and drop the unimplemented `context` mention, or rename
  `"job"` to `"context"` if the reviewer prefers keeping that name from the original design intent
  — naming is not load-bearing, the fetch-by-job-id mechanism is.

## In scope

1. `job_id: UUID | None = None` parameter on `SessionKeyProvider.get_session_key`.
2. New `_get_from_job` method + `"job"` branch.
3. Update the three `sessions_bus.py` call sites to pass `job_id=notification.job_id`.
4. Correct the class docstring's `Options:` line.
5. Unit tests: cache hit skips the fetch entirely (job_id not required in that path), `"job"`
   source with no `job_id` raises `ValueError`, successful fetch caches under `session_id`,
   non-2xx response propagates as `httpx.HTTPStatusError` (consistent with `_get_from_remote`'s
   existing behavior — not swallowed).

## Out of scope

- The server-side endpoint itself — bechtleav360/avs.ai.idac.service-sessions#194, this repo only
  consumes it.
- `vault` implementation (unrelated pre-existing gap).
- Any change to `JobNotification`'s fields — deliberately not adding `session_key` there, see
  Design above.
- Retry/backoff policy for the fetch — matches `_get_from_remote`'s current (no-retry) behavior;
  a separate concern if it needs hardening.

## Acceptance criteria

- **AC-1** `get_session_key(session_id, job_id=X)` with `source="job"` and a cache miss calls
  `GET {remote_url}/internal/jobs/{X}/session-key` and returns the key from the response.
- **AC-2** A subsequent call for the same `session_id` (different `job_id`, or none) hits the
  cache and makes no HTTP call.
- **AC-3** `source="job"` with no `job_id` raises `ValueError` before attempting any network call.
- **AC-4** `env`/`config`/`vault`/`remote` sources are unaffected — no behavior change for
  existing consumers (VerA's deployment, per `agents-document-analyser`'s CLAUDE.md, stays on
  whatever it currently uses).
- **AC-5** Docstring's `Options:` line matches the actual branch list in code.

## Constraints

- Backward compatible: `job_id` is optional and only required when `source == "job"`; every other
  source's call signature and behavior is unchanged.
- No new dependency — `httpx` is already used by `_get_from_remote`.

## Open questions

- Confirm the endpoint path/prefix (`/internal/...` vs. something else) once
  bechtleav360/avs.ai.idac.service-sessions#194's spec is approved — this repo's `_get_from_job`
  should match whatever that spec lands on.

## Related issues

- bechtleav360/avs.ai.project.pida#385 — where this was found live.
- bechtleav360/avs.ai.idac.service-sessions#194 — the server-side endpoint this depends on.
