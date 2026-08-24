# Spec: Add a job-scoped `"job"` source to `SessionKeyProvider`

**Issue:** bechtleav360/AVS.AI.Blueprint.AgenticService#76
**Companion (server contract):** bechtleav360/avs.ai.idac.service-sessions#196
**Status:** spec r3 — supersedes r2 (r2's server-side dependency was DENY'd; see below)

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

## r2 → r3: the server-side dependency changed shape again

r2 proposed reading `session_key` directly off the `job_created` SSE notification, because the
server-side companion spec's r2 (service-sessions#196) attached it there. That server-side r2 was
DENY'd: the agent SSE channel's replay buffer turned out to have no per-recipient access control
(a process-wide, capability-filtered-only 500-entry ring buffer, replayable by any `X-Api-Key`
holder via auto-registration), so putting a raw session key in that payload would have made every
dispatched key bulk-harvestable. The server-side r3 instead keeps `job_created` **completely
unchanged** and introduces a one-time, short-lived (15 min TTL), single-use fetch:
`GET /internal/jobs/{job_id}/session-key`, backed by storage that never touches the broadcast
path. Full reasoning in service-sessions#196's r3.

This reverts this repo's side back to a fetch-based source (closer to r1's shape, not r2's) — but
against a real, correctly-scoped endpoint this time, not r1's endpoint whose premise didn't hold.

## Root cause / gap (unchanged since r1)

The class docstring already gestures at the right shape — "Per-session keys passed via context
(Phase 3)" — but it was never implemented: `get_session_key`'s branch list is only
`env`/`config`/`vault`/`remote`, and the docstring's `Options:` line (`env, vault, context`) has
also drifted from the actual code (missing `config` and `remote`, listing unimplemented
`context`).

## Design

**New source: `"job"`.** Fetches the key once via
`GET {remote_url}/internal/jobs/{job_id}/session-key` (`X-Api-Key` auth), per
service-sessions#196's r3 contract:

```python
async def get_session_key(
    self, session_id: UUID | None = None, job_id: UUID | None = None
) -> str:
    cache_key = str(session_id) if session_id else "default"
    if self._cache is not None and cache_key in self._cache:
        return self._cache[cache_key]

    if self._source == "job":
        session_key = await self._get_from_job(job_id)
    elif self._source == "env":
        ...
    # ...existing branches unchanged...

    if self._cache is not None:
        self._cache[cache_key] = session_key
    return session_key

async def _get_from_job(self, job_id: UUID | None) -> str:
    if not job_id:
        raise ValueError("job_id required for 'job' source")
    if not self._remote_url:
        raise ValueError("sessions_service.session_key_remote_url not configured")
    url = f"{self._remote_url}/internal/jobs/{job_id}/session-key"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, headers={"X-Api-Key": self._api_key})
        response.raise_for_status()  # 404 (already claimed / expired / unknown) raises here
        return response.json()["session_key"]
```

- `job_id` is a new optional parameter on `get_session_key`, threaded from the three call sites in
  `sessions_bus.py` (lines 377, 421, 445) — all three already have `job_id` in scope from the
  notification they're handling.
- **The fetch is single-use server-side** (service-sessions#196 AC-2) — a second call for the
  same `job_id` 404s. This makes the client-side cache load-bearing in a way it wasn't for
  `env`/`config`/`remote`: once fetched, the cached value is the *only* copy this process can
  still obtain for that session. If the cache entry is evicted (TTL, default 3600s) before every
  job needing that key has been processed, there is no recovery — a retry would hit the
  already-consumed endpoint and 404. See Constraints.
- Reuses the existing `session_key_remote_url` / `api_key` config fields (already present for
  `remote`) rather than adding new ones.
- Fix the docstring's `Options:` line to list the actual implemented sources
  (`env, config, vault, remote, job`) and drop the unimplemented `context` mention.

## In scope

1. `job_id: UUID | None = None` parameter on `SessionKeyProvider.get_session_key`.
2. New `_get_from_job` method + `"job"` branch.
3. Update the three `sessions_bus.py` call sites to pass `job_id=notification.job_id`.
4. Correct the class docstring's `Options:` line.
5. Unit tests: cache hit skips the fetch entirely; `"job"` source with no `job_id` raises
   `ValueError` before any network call; successful fetch caches under `session_id`; a 404
   response (already-claimed/expired/unknown) propagates as `httpx.HTTPStatusError` rather than
   being swallowed or silently retried (a silent retry would always 404 given single-use — a
   test should assert there is no retry loop here).

## Out of scope

- The server-side endpoint and its storage — service-sessions#196, this repo only consumes it.
- `vault` implementation (unrelated pre-existing gap).
- `remote`/`_get_from_remote` — left in place, unused by any current consumer.
- Cache-eviction-vs-single-use hardening (e.g. pinning the TTL for `"job"`-sourced entries higher
  than the default, or re-deriving from a fresh notification if one arrives) — flagged in
  Constraints as a real gap, not solved here; the default cache TTL (3600s) comfortably exceeds
  this framework's own documented job-processing budgets today, so this is a latent risk, not a
  live bug.

## Acceptance criteria

- **AC-1** `get_session_key(session_id, job_id=X)` with `source="job"` and a cache miss calls
  `GET {remote_url}/internal/jobs/{X}/session-key` and returns the key from the response.
- **AC-2** A subsequent call for the same `session_id` (different `job_id`, or none) hits the
  cache and makes no HTTP call — this is now a correctness requirement, not just an optimization,
  since a second real fetch would 404.
- **AC-3** `source="job"` with no `job_id` raises `ValueError` before attempting any network call.
- **AC-4** A 404 from the endpoint (already claimed / expired / unknown `job_id`) raises
  `httpx.HTTPStatusError`, uncaught — the caller (`sessions_bus.py`) sees it as the job-processing
  failure it actually is, not a swallowed no-op.
- **AC-5** `env`/`config`/`vault`/`remote` sources are unaffected.
- **AC-6** Docstring's `Options:` line matches the actual branch list in code.

## Constraints

- Backward compatible: `job_id` is optional and only required when `source == "job"`.
- No new dependency — `httpx` is already used by `_get_from_remote`.
- **Named risk, not fixed here:** the single-use server contract means this framework's cache is
  the sole holder of the key after first fetch. A cache eviction (TTL expiry) before all
  processing for that session completes is unrecoverable under this design. Worth flagging back
  to whoever owns this framework's deployment defaults if a consumer's job-processing latency
  regularly approaches the cache TTL.

## Open questions

None blocking — the server contract is settled by service-sessions#196's r3.

## Related issues

- bechtleav360/avs.ai.project.pida#385 — where this was found live.
- bechtleav360/avs.ai.idac.service-sessions#196 — the server-side endpoint this depends on (r3).
