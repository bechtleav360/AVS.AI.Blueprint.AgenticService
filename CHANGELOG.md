# Changelog
## [0.6.0] - Planned

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
