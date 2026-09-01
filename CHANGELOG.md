# Changelog
## [Unreleased]

### Added
- **`SessionsJobHandler` can now mark a job `FAILED`** (#72). `SessionsApiClient` gains `fail_job(session_id, job_id, session_key, error)`, posting a `JobError`-shaped `{"message", "code"}` to the svc-sessions `/fail` endpoint (running→failed, live since 2026-06-24) — the write-side counterpart to the already-generic read side. A new overridable hook `SessionsJobHandler.failure_of(result) -> dict | None` lets a handler whose `process()` returns a failure *without raising* route that result to `fail_job` instead of `complete_job`; it defaults to `None` (complete), so existing consumers are unchanged until they override it. This unblocks `document-analyser`, whose `AnalyseBatchHandler` computes an internal "failed" outcome and returns it normally (bechtleav360/avs.ai.idac.agents-document-analyser#167, #169). Supersedes the `fail_job`-specific part of #41, whose "jmes-validator-only" premise never applied to `SessionsJobHandler` consumers.
- **`SessionKeyProvider` gains a `"job"` source** (#76). `env`/`config` only ever supported one static key for every session, which cannot work for consumers whose session keys are generated fresh per session and actually validated (encryption enforced) — the gap live-reproduced as `ValueError: Environment variable SESSION_KEY not set` immediately after a job dispatch (bechtleav360/avs.ai.project.pida#385). `source = "job"` fetches the key via `GET {session_key_remote_url}/internal/jobs/{job_id}/session-key?agent_id=<this agent's own id>` (bechtleav360/avs.ai.idac.service-sessions#194 Finding 2 / #196), threading a new optional `job_id` parameter through `get_session_key` from `SessionsBus`'s three call sites. A 409 (job already claimed by a different `agent_id`) raises the new `SessionKeyClaimConflictError`, distinct from the 404/`httpx.HTTPStatusError` case. `env`/`config`/`vault`/`remote` sources are unaffected.

### Changed
- **An unrecoverable exception from `process()` now marks the job `FAILED` instead of `COMPLETED`** (#72). Previously `ValueError` and any other non-retryable, non-`InvalidEventError` exception were routed to `complete_job` with an error-shaped result (`{"status": "failed", "error": ...}`), leaving the job's top-level status `COMPLETED`. They now route to `fail_job` (svc-sessions `FAILED`). This applies to **all** consumers on upgrade (unlike the opt-in `failure_of` hook). Note the downstream consequence: svc-sessions spawns pipeline-downstream jobs only on `COMPLETED`, so a step that now fails halts its chain rather than silently continuing on bad data.

## [0.6.4] - 2026-07-29

### Fixed
- **`EventProcessingService` no longer constructed when no event handlers are registered** (#67). `AppBuilder.build()` created it unconditionally, even for pure-scheduler or pure-REST agents that never route through the handler chain. Now gated on `registry.get_event_handler()`, mirroring the existing `EventPublishingService` guard.
- **`@traced` no longer binds/stamps arguments on every call when tracing isn't recording** (#65). Checks `span.is_recording()` right after opening the span and skips `inspect.signature().bind()` + attribute extraction for no-op spans (no OTel provider/exporter configured). Span creation and error-status handling are unchanged.
- **`MetricsRecorder` no longer recreates OTel token/latency instruments on every LLM call** (#64). `record()` called `meter.create_counter`/`create_histogram` on every invocation instead of once; both instruments are now created lazily on first use and cached on the instance. Also documents the previously-undocumented `token_metrics_enabled` config key.

## [0.6.3] - 2026-07-08

### Fixed
- **`SessionsBus` now reconciles jobs missed while disconnected** (#57). SSE is a live-only push
  transport, so jobs created during a restart, redeploy, or stream gap were never delivered and
  stayed `pending` on the server (observed: 9 `analyse.batch` jobs created before a reconnect that
  were never picked up). On every (re)connect the bus now reconciles two ways: (1) a REST
  **catch-up** — lists pending jobs for its capabilities (`GET /jobs?status=pending`) and dispatches
  each through the normal job path (best-effort; de-duplicated by the handler's idempotency guards;
  a listing failure never disturbs the live stream), and (2) **`Last-Event-ID` resume** — tracks the
  last SSE event id and sends `last_event_id` on reconnect so a same-process stream gap replays from
  the server ring buffer. A cold start omits `last_event_id` (catch-up covers it). Distinct follow-on
  to #45. A job stranded in `running` by a crashed agent is recovered server-side
  (avs.ai.idac.service-sessions#127) and then redelivered by this catch-up.

## [0.6.2] - 2026-07-06

### Fixed
- **`SessionsBus` registers with the dispatch registry before opening the SSE stream** (#45).
  Sessions v0.4.0 gates `GET /jobs/stream/sse` on a prior `POST /agents/register`; the bus now
  registers (idempotent) before every connect attempt and re-registers on reconnect, fixing the
  403 loop that broke all deployed agents. A pre-v0.4.0 server (404 on register) is handled as
  "legacy, proceed without registration". The real status/body of an SSE rejection is now logged
  instead of an opaque `SSEError`.
- **Keepalive comment frames are no longer logged as `Unknown SSE event type: message`** (#44).

### Changed
- **`SessionsBus` unregisters and drains in-flight jobs on graceful shutdown.** It stops the stream,
  waits for in-flight jobs (bounded by `job_timeout_seconds`, cancelling stragglers), then calls
  `DELETE /agents/{agent_id}` so the agent leaves the registry immediately instead of lapsing at TTL.
- Job notifications are parsed into a typed `JobNotification` model at the SSE boundary.
- **Business REST routers no longer carry a blanket `rest` OpenAPI tag.** `_build_rest_endpoints` mounted every `with_rest_api` router with `include_router(..., tags=["rest"])`, which stamps a redundant `rest` tag onto *every* operation on top of its own per-operation tag — so the entire business API collapses into a single `rest` group in Swagger UI. Routers are now mounted without the blanket tag; operations group by their real resource tags (set via the `RestApiBase` decorators), and untagged routes fall under FastAPI's `default`. Presentation only — no route/path/schema change. Downstream services that relied on the `rest` grouping should tag their routes (most already do).

## [0.6.1] - 2026-06-10

### Added
- **`SessionsJobHandler`** (`blueprint.agents.handler`) — shared job-lifecycle base for
  sessions-service SSE handlers (#19). Subclasses set `JOB_TYPE`, `PAYLOAD_MODEL`,
  `RESULT_MODEL` and implement `process()`; the base wraps fetch → validate → start →
  process → complete with two-stage idempotency (an in-flight guard for concurrent
  duplicates plus a **terminal-only** seen-set populated only on complete/cancel) and a
  centralised error→status mapping (cancel / complete-with-error / left-eligible-for-
  redelivery). Post-start retryable/critical failures are not silently dropped, but are
  not yet fully resumable — svc-sessions rejects `RUNNING→RUNNING` (409), so true resume
  awaits a re-pend/lease capability there (avs.ai.idac.service-sessions#59).
  Additive and backwards compatible — `EventHandlerBase` is unchanged.

### Fixed
- **OpenAPI app metadata now comes from config** (#11). `AppBuilder.build()` no longer
  hardcodes `version="0.1.0"`; it reads `app_version` (fallback `"0.0.0"`) alongside
  `app_name` (fallback `"blueprint-service"`) and `app_description` (fallback `""`). The
  misleading framework-internal description fallback is removed. Set `app_version` in a
  service's `settings.toml` to surface the real version at `/docs`.
- **`asbs dev` now uses the launching interpreter** (#15). The dev server subprocess
  spawned `"python"` literally, which on Windows with uv-managed venvs could resolve to
  uv's base interpreter and fail with `No module named uvicorn`. It now uses
  `sys.executable`, so the reload server runs in the same venv as `asbs`.
- **Kebab-case component names produce valid identifiers** (#3). `camel_to_snake` now
  normalizes hyphens, so kebab-case names no longer generate invalid Python identifiers.

## [0.5.0] - 2026-03-05

### Architecture Refactoring - Component System Streamlining

**Planned from Plan.md - 3 features ready for implementation**

#### Feature 3: Streamlined Base Package (Foundation)
- **BREAKING**: Promote concrete default implementations into `Component` base class
  - `get_name()`, `get_registry()`, `get_config()` default implementations
  - `link_config()`, `link_component_registry()` no longer abstract
  - `on_startup()`, `on_shutdown()` default no-op implementations
- Remove redundant overrides from `EventHandler`, `BusinessService`, `RestApi`, `AgentRuntime`
- Delete `interfaces.py` - `ComponentInterface` Protocol is unused

#### Feature 1: FastAPI Annotation-Based Route Registration
- **BREAKING**: `RestApi` decorator-based route registration
  - `RestApi.__init__` creates `APIRouter` and auto-discovers decorated methods
  - Routes defined with `@self.router.get()`, `@self.router.post()`, etc.
  - Remove `_register_routes()` abstract method
  - Remove `payload_type` init parameter and `Generic[PayloadT]`
- Update all 4 REST API examples to use annotation pattern

#### Feature 2: Scheduler Base Class
- **NEW**: `Scheduler` base class in `blueprint.agents.base`
  - Extends `Component` with full registry and config access
  - Constructor: `__init__(self, crontab: str, name: str = "Scheduler")`
  - Abstract method: `tick(self) -> None` - called on each cron interval
  - Background asyncio task with `croniter` for schedule evaluation
  - Automatic lifecycle management (startup/shutdown)
- Add `AppBuilder.with_scheduler(scheduler: Scheduler)` method
- Integrate into lifespan manager for proper startup/shutdown

### Sessions Service Integration - Architecture Planning 📋

**Documented in plan_blueprint.md - Ready for implementation**

Comprehensive 6-phase architecture plan for consuming jobs from Sessions Service via SSE:

#### Planned Components
- **JobConsumerService**: SSE connection management and job-to-CloudEvent conversion
- **SessionsApiClient**: REST API client for job lifecycle operations
- **JobHandler**: Optional convenience base class for job processing
- **SessionKeyProvider**: Abstract session key retrieval from multiple sources



### Testing & Quality Assurance

#### Example Verification System
- **NEW**: Comprehensive integration tests for all 7 example applications
  - `tests/integration/examples/test_examples.py` - 36 structure/config tests
  - `tests/verify_examples.py` - Automated startup verification script
  - All 36 structure tests passing ✓
  - 5/7 examples start without API keys, 2/7 require credentials



## [0.3.XX] - Planned
- RestAPI Baseclass for all RestAPIs
- Component Class as Baseclass for all Components (Baseclasses)
- Implement some standard methods in Component
- Scheduler in communication layer (Alternative to Events and API)

## [0.3.11] - 2025-12-22

### Highlights
- Added a  two-agent **Customer Support Q&A** example app and documented the new workflow, configuration guide, and config validation script.
- `Config.get_ai_config()` now understands both `model_*` and legacy `ai_model_*` keys plus plural/singular runtime sections.
- Health check logging is quiet unless something fails (new filter, toned-down actuator + provider logs).

## [0.3.10] - 2025-11-27

- [ ] Make the status of the Handler Result an Enum
- [ ]  Improve logging for parallel event consumption. Configure the logging formatter to always print the current event ID
- [ ]  Add endpoint to receive logs identified either bei span id or event id


## [0.3.9] - 2025-11-27

### Fixed
- Hardened `AgentBuilder.build()` so it always resolves the configured system prompt (either explicit or runtime default) before constructing `AgentRuntime`, raising helpful `ValueError`s when configuration is missing or the prompt cannot be loaded. This prevents the prior `TypeError: 'NoneType' object is not iterable` during agent startup.
- Added regression coverage around the updated builder behavior to ensure `PromptLoader` results are passed through to the runtime constructor and that misconfiguration is surfaced immediately.

### Documentation
- Reframed the integration testing guide into a black-box testing prompt for LLM-driven test generation, making the expected Dapr/respx workflow explicit and avoiding instructions that mock internal classes.

## [0.3.8] - 2025-11-26

### Added
- DAPR events are now automatically unwrapped

### New Cache introduced
- **Persistent Caching Layer**: New `CacheService` and `DiskCacheService` for high-performance disk-based caching
- `AppBuilder.with_cache()` method to enable caching with fluent interface
- `ComponentRegistry.get_cache()`, `has_cache()` methods for cache management

#### Features
- **Order-independent key hashing**: `{"a":1,"b":2}` and `{"b":2,"a":1}` produce identical hashes
- **JSON string normalization**: JSON strings are automatically parsed and sorted for consistent hashing
- **Recursive JSON handling**: Nested JSON structures are properly normalized
- **Lazy TTL cleanup**: Expired entries are cleaned up only when accessed
- **Cache statistics**: `get_stats()` method for monitoring cache usage

#### Configuration
New cache settings in `settings.toml`:
```toml
[cache]
cache_dir = ".cache/blueprint"           # Cache directory path
size_limit = 1000000000                  # 1GB max size
eviction_policy = "least-recently-used"  # LRU eviction
default_ttl = 3600                       # 1 hour default TTL
```

#### Dependencies
- Added `diskcache-rs>=0.4.4` for high-performance persistent caching

## [0.3.4]- 2025-11-25

### Added
- New `/info` actuator endpoint exposing app name, version, and all dependency versions.
- [ServiceInfo](/src/blueprint/agents/models/status.py:8:0-25:5) model for structured `/info` responses.
- Actuator links (`/info`, `/status/env`, `/status/llm`, `/status/build`) in root `/` metadata.
- Supporting classes in component registry in addition to names
- Fetching an unregistered component now throws an exception
- Added get_config() to all base classes
- Simplied Prompt Loading, removed the need to give package root and config path to AgentBuilder

### New Feature: Dapr Retry Flow
We are strictly avoiding the DROP status for errors because Dapr deletes DROP messages immediately.

To ensure failed messages eventually reach the Dead Letter Queue (DLQ), we use the following flow:

- Application Error: Your code throws an exception (e.g., 500 Internal Error).
- Return RETRY: We catch this and tell Dapr to RETRY.
- Dapr Retries: Dapr will retry the message N times based on your configured Resiliency Policy.
- Move to DLQ: Once the max retries are exhausted, Dapr automatically moves the message to the configured Dead Letter Topic.



## [0.3.0] - 2025-11-24

### Changed
- **BREAKING:** Refactored `AppBuilder` constructor - now requires `Config` object instead of `settings_files` and `root_path` parameters
- **BREAKING:** Moved base classes to unified `blueprint.agents.base` module: `EventHandler`, `AgentRuntime`, `RestApi`, `BusinessService`
- Handler storage refactored from dict to list to support multiple handlers with identical names
- All components now use async `on_startup()` lifecycle hooks to retrieve dependencies from registry

### Added
- `AppBuilder.with_service()` method to register business services
- Async lifecycle management for all components via `on_startup()` and `on_shutdown()` hooks

### Removed
- `AgentRuntime` from `blueprint.agents.agent` module (moved to `blueprint.agents.base`)
- `EventHandler` from `blueprint.agents.handler` module (moved to `blueprint.agents.base`)
- `RestApi` from `blueprint.agents.api.rest` module (moved to `blueprint.agents.base`)
- `package_root` parameter from `AgentBuilder` - no longer needed with new prompt loading

### Fixed
- All integration and unit tests updated for new architecture
- FastAPI `TestClient` fixtures now properly manage lifespan to run startup hooks
- Example applications refactored to use new `AppBuilder(config=Config(...))` pattern

## [0.2.8] - 2025-11-24

### Added
- New `MetricsRecorder` and `MetricsExtractor` classes for modular metrics handling
- `with_metrics(enabled: bool = True)` builder method to toggle metrics logging
- `AgentRuntime.get_prompt(prompt_name)` method for lazy-loaded prompt retrieval with caching
- Complete prompt handling redesign with simplified API

### Changed
- **BREAKING:** Simplified `AgentBuilder` prompt API - replaced 4 methods with single `with_system_prompt(prompt: str | None = None)`
- Extracted metrics functionality from `AgentBuilder` to dedicated `metrics.py` module
- Logging levels upgraded from DEBUG to INFO for builder configuration operations
- Prompt loading strategy changed from pre-load at build time to lazy-load on demand
- Removed `_prompts` pre-loading from `AgentBuilder` - now uses lazy loading with caching in `AgentRuntime`
- Cleaned up public API exports - removed unused factory classes

### Removed
- `AgentFactory` - not used, AgentBuilder creates agents directly
- `ResponseHandlerFactory` - not integrated into agent creation flow
- `_prompts` attribute from `AgentBuilder` (prompts now lazy-loaded)
- `_load_prompt()` internal method from `AgentBuilder`
- Unused factory and handler exports from public API

### Deprecated
- `with_system_prompt_text()` - use `with_system_prompt(prompt_text)` instead
- `with_system_prompt_file()` - use `with_system_prompt()` to load from config
- `with_system_prompt_from_config()` - use `with_system_prompt()` instead
- `with_prompt()` - use `agent.get_prompt(prompt_name)` for lazy loading instead
- `AgentRuntime.prompts` property - use `agent.get_prompt(name)` instead
- `AgentRuntime.register_prompt()` - use `agent.get_prompt(name)` instead

### Fixed
- All 73 unit tests passing with backward compatibility maintained
- Performance improved by eliminating unnecessary pre-loading of prompts

### Migration Guide
**Old (Deprecated):**
```python
agent = (
    AgentBuilder(config)
    .with_model_from_config()
    .with_system_prompt_text("prompt")
    .with_prompt("template")
    .build()
)
prompt = agent.prompts["template"]
```

**New (Recommended):**
```python
agent = (
    AgentBuilder(config)
    .with_model_from_config()
    .with_system_prompt("prompt")  # or .with_system_prompt() to load from config
    .build()
)
prompt = agent.get_prompt("template")  # lazy-loaded and cached
prompt = prompt.format(difficulty="hard")
```

### Notes
- ✅ All 73 unit tests passing
- ✅ Simpler, cleaner API with lazy loading and caching
- ✅ Better performance - no unnecessary pre-loading
- ✅ Clear separation of concerns - builder sets system prompt, runtime loads instruction prompts

## [0.2.6] - 2025-11-23

### Added
- Handlers can now return `list[HandlerResult]` to publish multiple events from a single handler
- Added 6 new tests for multiple handler results feature

### Changed
- `EventHandler.handle()` return type now includes `list[HandlerResult]`
- `ProcessingService.process_event()` now publishes each result with `event_type` separately
- `_ResultBuilder.extract_handler_result()` detects and handles list of results

### Fixed
- Proper handling of mixed results where some have `event_type=None`
- OpenTelemetry tracing now includes result count for multi-result scenarios

### Notes
- ✅ Fully backward compatible - all existing code continues to work
- ✅ All 137 unit tests passing (6 new tests added)
