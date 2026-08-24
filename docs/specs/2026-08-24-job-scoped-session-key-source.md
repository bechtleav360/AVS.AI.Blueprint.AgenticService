# Spec: Add a job-scoped `"job"` source to `SessionKeyProvider`

**Issue:** bechtleav360/AVS.AI.Blueprint.AgenticService#76
**Companion (server contract):** bechtleav360/avs.ai.idac.service-sessions#196
**Status:** spec r4 — supersedes r3 (server contract changed again; see below)

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

## r3 → r4: the server contract added agent-scoped claiming and a new status code

service-sessions#196 went through a further review round after r3 was written. Two more findings
there (a guardrail blind spot, and a security gap where the fetch endpoint could turn a
harvested `job_id` into a live session key) resulted in:

- The endpoint gained a required `agent_id` query parameter — the *first* caller to fetch a given
  `job_id` claims it; later calls from a different `agent_id` get **409**, not the key. This
  narrows (doesn't cryptographically close — `agent_id` is self-declared) the risk that a
  `job_id` harvested via the SSE replay buffer could be traded for a live key by someone other
  than the actually-dispatched agent.
- The fetch is no longer single-use — repeat calls from the *same* `agent_id` within the 15-minute
  TTL window succeed (server-side r4/r5 change, made for crash/cache-eviction recoverability).
  This actually **removes** r3's biggest named risk here (client cache as sole holder of the key)
  — see Constraints.

This repo's side needs one addition over r3: pass this agent's own `agent_id` on the fetch, and
handle 409 as a distinct, real outcome (not just another failure to raise-and-forget).

## Root cause / gap (unchanged since r1)

The class docstring already gestures at the right shape — "Per-session keys passed via context
(Phase 3)" — but it was never implemented: `get_session_key`'s branch list is only
`env`/`config`/`vault`/`remote`, and the docstring's `Options:` line (`env, vault, context`) has
also drifted from the actual code.

## Design

**New source: `"job"`.** Fetches the key via
`GET {remote_url}/internal/jobs/{job_id}/session-key?agent_id=<this agent's own id>`
(`X-Api-Key` auth), per service-sessions#196's current contract:

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
    if not self._agent_id:
        raise ValueError("agent_id not set — SessionKeyProvider must be started after SessionsBus")
    url = f"{self._remote_url}/internal/jobs/{job_id}/session-key"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            url, params={"agent_id": self._agent_id}, headers={"X-Api-Key": self._api_key}
        )
        if response.status_code == 409:
            raise SessionKeyClaimConflictError(
                f"job {job_id}'s session key was already claimed by a different agent"
            )
        response.raise_for_status()  # 404 (expired/unknown) raises here
        return response.json()["session_key"]
```

- **`self._agent_id`**: `SessionKeyProvider` needs the same `agent_id` `SessionsBus` already
  tracks (`sessions_bus.py:65,85`). Threaded in at construction/startup rather than duplicating
  config resolution — `SessionsBus` passes its own `self._agent_id` to the key provider it owns,
  or both read the same `sessions_config.agent_id` value. Either wiring works; the concrete choice
  is an implementation detail, not a design question.
- **New exception**: `SessionKeyClaimConflictError` (409) is distinct from "not found/expired"
  (404, `httpx.HTTPStatusError`) — a caller catching this can log "another agent instance already
  claimed this job" rather than treating it identically to "the key is simply gone." Only relevant
  today if this agent type is ever scaled to multiple replicas of one capability (not the current
  deployment shape, per pida's own document-analyser CLAUDE.md).
- `job_id` remains a new optional parameter on `get_session_key`, threaded from the three call
  sites in `sessions_bus.py` (lines 377, 421, 445) — unchanged from r3.
- **Caching is now genuinely just an optimization again**, not a correctness requirement — see r3
  vs. r4 in Constraints. The server no longer discards the key on first read, so a cache miss on a
  later call for the same `job_id`/`agent_id` simply re-fetches successfully instead of 404ing.
- Fix the docstring's `Options:` line to list the actual implemented sources
  (`env, config, vault, remote, job`).

## In scope

1. `job_id: UUID | None = None` parameter on `SessionKeyProvider.get_session_key`.
2. `self._agent_id` available to `SessionKeyProvider` (wired from `SessionsBus` or shared config).
3. New `_get_from_job` method + `"job"` branch, sending `agent_id` and handling 409 distinctly
   from 404.
4. New `SessionKeyClaimConflictError`.
5. Update the three `sessions_bus.py` call sites to pass `job_id=notification.job_id`.
6. Correct the class docstring's `Options:` line.
7. Unit tests: cache hit skips the fetch; `"job"` source with no `job_id` raises `ValueError`
   before any network call; missing `agent_id` raises `ValueError` before any network call; 409
   raises `SessionKeyClaimConflictError`, not swallowed or conflated with 404; successful fetch
   caches under `session_id`; a repeat fetch after a cache miss (simulating eviction) for the same
   `job_id`/`agent_id` succeeds rather than assuming failure (r4 behavior change from r3).

## Out of scope

- The server-side endpoint and its storage — service-sessions#196, this repo only consumes it.
- The pre-existing SSE replay/auto-registration identity gap the server-side spec names as the
  residual risk this narrows — service-sessions#198, a server-side fix, nothing to do here.
- `vault` implementation (unrelated pre-existing gap).
- `remote`/`_get_from_remote` — left in place, unused by any current consumer.

## Acceptance criteria

- **AC-1** `get_session_key(session_id, job_id=X)` with `source="job"` and a cache miss calls
  `GET {remote_url}/internal/jobs/{X}/session-key?agent_id=<self>` and returns the key.
- **AC-2** A subsequent call for the same `session_id` hits the cache and makes no HTTP call.
- **AC-3** `source="job"` with no `job_id` raises `ValueError` before any network call.
- **AC-4** `agent_id` unset raises `ValueError` before any network call.
- **AC-5** A 409 response raises `SessionKeyClaimConflictError`, distinguishable from the 404
  case (`httpx.HTTPStatusError`).
- **AC-6** A cache miss for a `job_id` already successfully fetched once (simulating eviction)
  succeeds on retry — no longer assumed to 404, since the server is no longer single-use.
- **AC-7** `env`/`config`/`vault`/`remote` sources are unaffected.
- **AC-8** Docstring's `Options:` line matches the actual branch list in code.

## Constraints

- Backward compatible: `job_id` is optional and only required when `source == "job"`.
- No new dependency — `httpx` is already used by `_get_from_remote`.
- **r3's named risk is resolved, not just documented, by the server-side change**: since the
  server fetch is no longer single-use, a cache eviction before job completion is now recoverable
  (a fresh fetch with the same `agent_id` succeeds). r3's "cache is the sole holder of the key"
  framing no longer applies.
- **New, smaller residual risk**: if this agent type ever runs multiple replicas of one
  capability, whichever replica's `agent_id` claims a `job_id` first is the only one that can
  fetch it again — a replica that didn't win the race gets 409 forever for that job, even though
  it's the one actually processing it (if job routing and key-claiming ever get out of sync
  between replicas). Not reachable in today's single-instance-per-capability deployment.

## Open questions

None blocking — the server contract is settled by service-sessions#196's current revision.

## Related issues

- bechtleav360/avs.ai.project.pida#385 — where this was found live.
- bechtleav360/avs.ai.idac.service-sessions#196 — the server-side endpoint this depends on.
- bechtleav360/avs.ai.idac.service-sessions#198 — the residual identity-scoping gap, server-side,
  nothing to build here.
