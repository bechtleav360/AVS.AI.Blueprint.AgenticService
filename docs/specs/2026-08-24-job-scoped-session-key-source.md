# Spec: Read the session key directly off the job dispatch notification

**Issue:** bechtleav360/AVS.AI.Blueprint.AgenticService#76
**Companion (server contract):** bechtleav360/avs.ai.idac.service-sessions#194
**Status:** spec r2 — supersedes r1 (r1's server-side dependency was DENY'd; see below)

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

## r1 → r2: the server-side dependency changed shape

r1 proposed a `"job"` source that fetched the key via a new server endpoint
(`GET .../jobs/{job_id}/session-key`). Review on the server-side companion spec
(bechtleav360/avs.ai.idac.service-sessions#196) found that endpoint isn't implementable: the
server never persists the raw session key (only its SHA-256 hash, for comparison), so there is no
later moment for a fetch to return it from. The corrected server-side design instead attaches
`session_key` directly to the `job_created` SSE payload, at the one point the server actually has
the key (synchronously, inside the request that creates the job). Full reasoning in #196's spec.

This *simplifies* this repo's side of the fix: no new HTTP call, no new endpoint dependency, no
new failure mode from a network round-trip mid-job. The key is already inbound on the same
connection that delivered the job notification.

## Root cause / gap (unchanged from r1)

The class docstring already gestures at the right shape — "Per-session keys passed via context
(Phase 3)" — but it was never implemented: `get_session_key`'s branch list is only
`env`/`config`/`vault`/`remote`, and the docstring's `Options:` line (`env, vault, context`) has
also drifted from the actual code (missing `config` and `remote`, listing unimplemented
`context`).

## Design

**`JobNotification` gains an optional field**, populated only when the sessions service sends one
(backward compatible — older/other sessions-service versions simply omit it):

```python
# models/sessions.py
class JobNotification(BaseModel):
    ...
    session_key: str | None = None
```

`model_config = ConfigDict(extra="allow")` already meant an unrecognised `session_key` key would
have passed through silently before; declaring it explicitly makes it a real, typed, documented
field instead of relying on that fallback.

**New source: `"context"`** (reclaiming the docstring's original Phase-3 name, since the mechanism
now genuinely matches what that name always implied — the key travels with the request/event
context, not a side-channel fetch):

```python
async def get_session_key(
    self, session_id: UUID | None = None, notification_key: str | None = None
) -> str:
    cache_key = str(session_id) if session_id else "default"
    if self._cache is not None and cache_key in self._cache:
        return self._cache[cache_key]

    if self._source == "context":
        if not notification_key:
            raise ValueError("session_key not present on notification; source='context' requires it")
        session_key = notification_key
    elif self._source == "env":
        ...
    # ...existing branches unchanged...

    if self._cache is not None:
        self._cache[cache_key] = session_key
    return session_key
```

- `notification_key` is a new optional parameter, threaded from the three call sites in
  `sessions_bus.py` (lines 377, 421, 445) as `notification_key=notification.session_key` — all
  three already have the `notification` object in scope.
- **Caching is unchanged in shape**, still keyed by `session_id` — a `"context"` resolution
  populates the same `TTLCache`, so if the *same* session's key arrives again on a later job
  notification (or the cache is still warm from an earlier one), redundant work is avoided the
  same way the existing sources already benefit from the cache.
- Fix the docstring's `Options:` line to list the actual implemented sources
  (`env, config, vault, remote, context`).
- `remote`/`_get_from_remote` stays as-is, dead-ish code for now (no server implements it), not
  removed — out of scope to touch it here.

## In scope

1. `session_key: str | None = None` field on `JobNotification`.
2. `notification_key: str | None = None` parameter on `SessionKeyProvider.get_session_key`.
3. New `"context"` branch (no new async method needed — it's a direct assignment, not a fetch).
4. Update the three `sessions_bus.py` call sites to pass `notification_key=notification.session_key`.
5. Correct the class docstring's `Options:` line.
6. Unit tests: `"context"` source with `notification_key` present populates and caches correctly;
   `"context"` with `notification_key=None` raises `ValueError` before doing anything else; a
   second call for the same `session_id` hits the cache regardless of whether a fresh
   `notification_key` was supplied.

## Out of scope

- The server-side change itself — bechtleav360/avs.ai.idac.service-sessions#196, this repo only
  consumes its output.
- `vault` implementation (unrelated pre-existing gap).
- `remote`/`_get_from_remote` — left in place, unused by any current consumer, not this spec's
  concern to remove or fix.
- Any handling for the orphan-reaper re-announce case where no key is attached server-side
  (service-sessions#196's Open Questions) — this repo's cache-based mitigation for that case is
  already implicit in the caching behavior above (a repend within the TTL window resolves from
  cache without needing a fresh `notification_key`); nothing further to build here.

## Acceptance criteria

- **AC-1** `get_session_key(session_id, notification_key=X)` with `source="context"` and a cache
  miss returns `X` and caches it under `session_id` — no network call.
- **AC-2** A subsequent call for the same `session_id` (with or without a fresh
  `notification_key`) hits the cache.
- **AC-3** `source="context"` with `notification_key=None` raises `ValueError` immediately.
- **AC-4** `env`/`config`/`vault`/`remote` sources are unaffected — no behavior change for
  existing consumers (VerA's deployment, per `agents-document-analyser`'s CLAUDE.md, stays on
  whatever it currently uses).
- **AC-5** Docstring's `Options:` line matches the actual branch list in code.
- **AC-6** `JobNotification.session_key` defaults to `None` and does not break parsing of
  notifications from a sessions-service version that doesn't send it.

## Constraints

- Backward compatible: `notification_key` is optional and only required when
  `source == "context"`; every other source's call signature and behavior is unchanged.
- No new dependency (this version needs no `httpx` call at all, unlike r1).

## Open questions

None blocking — the server contract is settled by service-sessions#196's r2.

## Related issues

- bechtleav360/avs.ai.project.pida#385 — where this was found live.
- bechtleav360/avs.ai.idac.service-sessions#196 — the server-side change this depends on (r2, the
  design that made this simpler).
