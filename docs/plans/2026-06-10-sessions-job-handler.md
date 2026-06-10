# Plan — Promote `SessionsJobHandler` to framework

**Issue:** bechtleav360/...blueprint#19
**Spec source:** issue #19 body (acceptance criteria) + analyser#13 (lifecycle parity reference)
**Repo:** `blueprint.agent-service` (code-follows rule — the framework change lives here)

## Goal

Add `blueprint.agents.handler.SessionsJobHandler` — a shared base that wraps the
sessions job lifecycle (fetch → validate → start → process → complete) so the four
SSE-consuming agents stop duplicating ~100 LOC each.

## Resolved design decisions

1. **`process()` signature — raw dict context.**
   `async def process(self, payload: PAYLOAD_MODEL, context: dict[str, Any]) -> RESULT_MODEL`.
   No new `HandlerContext` type. Matches the existing `EventHandlerBase` convention; the
   base unpacks `session_id`/`job_id`/`session_key`/`sessions_api_client` from the dict for
   its own lifecycle calls, then passes the same dict through to `process()`.

2. **Error → terminal-state mapping — verified against svc-sessions.**
   svc-sessions `JobStatus` enum defines `FAILED`, but there is **no transition into it**
   (`RUNNING→COMPLETED`, `RUNNING→CANCELLED` only) and **no API to set it**. Only COMPLETED
   and CANCELLED are reachable. Mapping:

   | `process()` raises | Base action | Terminal state |
   |---|---|---|
   | (validation fails, before `process`) `InvalidEventError` | `cancel_job(reason=...)` | CANCELLED |
   | `InvalidEventError` | `cancel_job(reason=...)` | CANCELLED |
   | `RetryableHandlerError` | re-raise | PENDING (SessionsBus leaves it) |
   | `OSError`, `TimeoutError` | wrap → re-raise `RetryableHandlerError` | PENDING |
   | `ValueError`, any other `Exception` | `complete_job(result={"status":"failed","error":...})` | COMPLETED (result signals failure) |

   The base **owns** the mapping (calls `cancel_job`/`complete_job` itself); it only re-raises
   for the retryable bucket so SessionsBus's existing handler leaves the job pending.
   `InvalidEventError` is NOT re-raised after the base cancels (avoids double-cancel +
   illegal `CANCELLED→CANCELLED` transition).

3. **`agent_id`** read from `self.config["sessions_service"]["agent_id"]` on `on_startup`;
   required (raise `ValueError` if missing — no hardcoded default).

## Lifecycle order (`handle_event`)

1. Unpack `session_id`, `job_id`, `session_key`, `api_client` from `context`.
2. **Idempotency — two-stage (revised per review).** A single permanent seen-set added
   *before* a durable lifecycle point would strand jobs: a transient `get_job_detail`/
   `start_job` failure raises `RetryableHandlerError`, SessionsBus leaves the job PENDING,
   and a later replayed `job_created` would be dropped because the id is already "seen".
   Use the analyser#13 model:
   - **In-flight guard** — synchronous check-and-add on `_in_flight: set[UUID]` at entry
     (no `await` between test and `add`). Handles *concurrent* duplicate notifications.
     Removed in a `finally` so a failed pre-start attempt is retryable.
   - **Terminal seen-set** — `_seen: set[UUID]`, id added **only after `start_job` succeeds**.
     Handles *replayed* notifications for an already-started/completed job.
   - Duplicate hitting either guard → log + return `None` (no-op). Transient pre-start
     failure leaves the id in *neither* set → a later duplicate proceeds normally.
3. `get_job_detail` → raw payload dict.
4. Validate payload → `PAYLOAD_MODEL` (`InvalidEventError` on failure → cancel; do this
   **before** `start_job` so we never start a job we immediately fail).
5. `start_job(session_id, job_id, agent_id, session_key)` → on success add `job_id` to `_seen`.
6. `result = await self.process(payload, context)` → `RESULT_MODEL`.
7. `complete_job` with retry (3 attempts, 2s backoff) on transient `httpx` errors.
8. Error mapping per table above.
9. Structured log line per stage: `session_id`, `job_id`, `job_type`, `status`, `duration_ms`.

`get_job_detail`/`start_job` raising transient `httpx` errors → wrap → `RetryableHandlerError`
(consistent with the `OSError`/`TimeoutError` bucket), so SessionsBus retry semantics are preserved.

## Surface

```python
class SessionsJobHandler(EventHandlerBase, ABC):
    JOB_TYPE: ClassVar[str]
    PAYLOAD_MODEL: ClassVar[type[BaseModel]]
    RESULT_MODEL: ClassVar[type[BaseModel]]

    async def can_handle_event(self, event, context) -> bool:
        return event.type == f"sessions.job.created.{self.JOB_TYPE}"

    async def handle_event(self, event, context) -> HandlerResult | None: ...  # lifecycle, final

    @abstractmethod
    async def process(self, payload: BaseModel, context: dict[str, Any]) -> BaseModel: ...
```

- Export `SessionsJobHandler` from `blueprint/agents/handler/__init__.py`.
- `can_handle_event` returning `False` for unknown `job_type` satisfies AC-7 (unknown type
  ignored, not raised) — no extra code.

## Steps

1. **TDD first** — write `tests/.../test_sessions_job_handler.py` covering: happy path,
   concurrent duplicate `job_id` no-op, replayed duplicate after `start_job` no-op,
   **transient `get_job_detail` failure then later duplicate proceeds** (not stranded),
   **transient `start_job` failure then later duplicate proceeds**, payload validation
   failure → cancel, `process` raising `ValueError`/generic `Exception` → complete-with-
   error-result, `process` raising `OSError`/`TimeoutError` → `RetryableHandlerError`
   (pending), `complete_job` retry then exhaustion, unknown `job_type` no-op. Mock
   `SessionsApiClient`.
2. Implement `src/blueprint/agents/handler/sessions_job_handler.py`.
3. Wire export in `handler/__init__.py` (`__all__`).
4. **CHANGELOG entry under the existing `[0.6.0]` section only. Do NOT touch
   `pyproject.toml` version** — `AGENTS.md` states versioning is handled by CI publishing;
   manual bumps are forbidden. (Supersedes the issue's "SemVer minor bump" in AC-4: the
   minor bump is the publish pipeline's job, the changelog entry is ours.)
5. `ruff check` + `black` + `mypy` + `pytest`.

## Test scenarios → acceptance criteria

| Scenario | AC |
|---|---|
| `test_happy_path_runs_full_lifecycle` | AC-1, AC-2 |
| `test_concurrent_duplicate_job_id_is_noop` (in-flight guard) | AC-3 (analyser#13 AC-5) |
| `test_replayed_duplicate_after_start_is_noop` (terminal seen-set) | AC-3 |
| `test_transient_get_job_detail_failure_then_duplicate_proceeds` | AC-3 (anti-stranding) |
| `test_transient_start_job_failure_then_duplicate_proceeds` | AC-3 (anti-stranding) |
| `test_invalid_payload_cancels_job` | AC-3 |
| `test_value_error_completes_with_failed_result` | AC-3 |
| `test_oserror_raises_retryable_leaves_pending` | AC-3 |
| `test_generic_exception_completes_with_failed_result` | AC-3 |
| `test_complete_job_retry_then_success` / `test_retry_exhaustion` | AC-3 |
| `test_unknown_job_type_not_handled` | AC-5 |
| export importable; `EventHandlerBase` untouched | AC-1, AC-5 |

## Scope findings (surfaced, not fixed here)

- **`SessionsApiClient.cancel_job` posts to `/sessions/{sid}/jobs/{jid}/cancel`, but svc-sessions
  (`api/jobs.py`) exposes no such route.** Pre-existing client/server mismatch — the cancel
  path may 404 at runtime. Out of scope for #19; will file a svc-sessions follow-up issue and
  link it. Unit tests assert the base *calls* `cancel_job` (mocked); they do **not** claim the
  invalid-payload cancel path is proven end-to-end against a live svc-sessions.
- **`JobStatus.FAILED` is dead** (unreachable). analyser#13 AC-4 "marks job failed" is
  aspirational; real mechanism is cancel-with-reason or complete-with-error-result.

## Out of scope (per issue)

Cross-restart idempotency, progress/partial-result publishing, IMAP sources, the per-agent
migration PRs (post-release).

## Risk

Base change ripples to all consumers → keep base small + abstract, SemVer minor, land before
second consumer migrates. Unbounded idempotency `set` — acceptable for current load (noted).

## Rollback

Pure addition (new file + one export line + CHANGELOG). Revert the commit; no consumer
depends on it until migration PRs land.
