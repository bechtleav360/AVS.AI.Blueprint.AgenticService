# Unit Tests — `blueprint.agents.services`

Test coverage for `src/blueprint/agents/services/`.

---

## File overview

| File | Class under test | What is covered |
|---|---|---|
| `eventing/test_event_processing_service.py` | `EventProcessingService` | `_extract_handler_results` (None/HandlerResult/list/dict variants), `_build_result` (message text, request_id, result list), `_unwrap_dapr_event` (passthrough / CloudEvent inner / dict inner / missing type / unexpected type), lifecycle no-ops, `process_rest_request` delegates to `process_event` with correct event shape |
| `eventing/test_event_publishing_service.py` | `EventPublishingService` | `on_startup` wires client and config, `_get_pub_config` raises before startup, `get_topic_for_event_type` / `get_available_event_types`, `publish_event` (topic mapping, explicit topic override, missing mapping raises, sets default source, result shape), `publish_handler_event` (no mapping → skip, loop prevention → skip, normal → publishes), `publish_status_event` type format and delegation |
| `infrastructure/test_disk_cache_service.py` | `DiskCacheService` | `set`/`get` (string/dict/list keys, namespace isolation), `delete` (return values), `exists` (before/after set/delete), `clear` (namespace-scoped and full), TTL expiration via mocked `time.time`, `hash` consistency for string/list/dict inputs, `list_namespaces`, `list_values` (content, TTL-entry exclusion, limit), `get_stats` field presence, lifecycle, context-manager protocol |
| `sessions/test_api_client.py` | `SessionsApiClient` | `on_startup` (valid config, missing config/base_url/api_key → ValueError), `on_shutdown` (closes client, no-op when uninitialised), `get_job_details`/`start_job`/`complete_job`/`cancel_job` (URL shape, required headers, payload contents, uninitialised guard) |
| `sessions/test_key_provider.py` | `SessionKeyProvider` | `on_startup` (initialises cache, reads source/env_var from config, missing config → ValueError), `on_shutdown` (clears cache, no-op when uninitialised), `get_session_key` (env hit/miss, config source, vault → NotImplementedError, unknown source, cache-hit bypass, result cached after fetch), `invalidate_cache` (default and per-session key removal, no-op when empty/uninitialised) |

---

## Fixtures

### `services/conftest.py`

| Fixture | Scope | Purpose |
|---|---|---|
| `reset_component_state` | function / **autouse** | Patches `CorrelationContextProvider`, resets `Component.shared_config` and `Component.shared_registry` after every test |
| `mock_config` | function | `MagicMock(spec=Config)` injected via `Component.configure` |
| `mock_registry` | function | `MagicMock(spec=Registry)` stored in `Component.shared_registry` |

### `services/eventing/conftest.py`

| Fixture | Scope | Purpose |
|---|---|---|
| `cloud_event` | function | Minimal valid `CloudEvent` for eventing tests |
| `pub_config` | function | `EventPublishingConfig` with two topic mappings (`test.event → test-topic`, `other.event → other-topic`) |
| `mock_io_client` | function | `MagicMock` with `publish = AsyncMock()` |
| `event_publishing_service` | function | `EventPublishingService` with `_pub_config` and `_client` pre-set; `mock_config.get.return_value = "test-agent"` to satisfy CloudEvent source validation |
| `event_processing_service` | function | `EventProcessingService()` with `mock_registry` and `mock_config` active |

### `services/sessions/conftest.py`

| Fixture | Scope | Purpose |
|---|---|---|
| `sessions_config` | function | Minimal valid `sessions_service` config dict |
| `api_client` | function | Fresh `SessionsApiClient` — not started |
| `mock_http_client` | function | `AsyncMock` simulating `httpx.AsyncClient` with `get`/`post`/`aclose` and a 200-like `mock_response` |
| `started_api_client` | function | `api_client` with `_base_url`, `_api_key`, and `_client` pre-set (bypasses `on_startup`) |
| `key_provider` | function | Fresh `SessionKeyProvider` — not started |
| `started_key_provider` | function | `key_provider` with `TTLCache`, `_source="env"`, and `_env_var` pre-set (bypasses `on_startup`) |

---

## Decisions

### `process_event` is not unit-tested directly

`process_event` orchestrates `HandlerChain`, sets correlation context, dispatches to `EventPublishingService`, and wraps all errors. Exercising it end-to-end requires registered handlers, a working registry, and wired publishing — integration territory. Unit tests cover only the static helpers (`_extract_handler_results`, `_build_result`) and `_unwrap_dapr_event`. `process_rest_request` is tested by patching `process_event` and asserting on the constructed `CloudEvent` shape.

### `_unwrap_dapr_event` uses `model_construct` for non-dict `data`

`GenericCloudEvent = CloudEvent[dict[str, Any]]`, so Pydantic validation rejects a `CloudEvent` instance as `data`. Tests for the "inner CloudEvent" and "unexpected payload type" branches use `model_construct` to bypass validation and produce the precise runtime state that the production code handles.

### `_extract_handler_results` does not handle plain non-dict values

`HandlerResult.data` is typed `dict[str, Any] | None`. The fallback branch `return HandlerResult(event_type=None, data=value, metadata={})` raises a Pydantic `ValidationError` for non-dict, non-`HandlerResult` inputs (e.g., strings). Tests cover only the reachable cases: `None`, `HandlerResult`, `list[HandlerResult]`, and dict variants.

### `event_publishing_service` fixture sets `mock_config.get.return_value = "test-agent"`

`publish_event` and `publish_handler_event` call `self.config.get("app_name", ...)` to build the `CloudEvent` source field. A plain `MagicMock` return value fails `CloudEvent.source` string validation. The fixture wires a string return value so all publish tests get a valid event without per-test config setup.

### `DiskCacheService` tests use `tmp_path` with a real `diskcache_rs` cache

`diskcache_rs` is a production dependency and is always available in CI. Using a real cache exercises the actual persistence, TTL storage, and namespace logic rather than mocking the underlying library. TTL expiration is tested by patching `time.time` in `blueprint.agents.services.infrastructure.cache_service`.

### `SessionKeyProvider` — `if self._cache:` bug fixed to `if self._cache is not None:`

`TTLCache` inherits `__bool__` from `MutableMapping`, which delegates to `__len__`. An empty cache is falsy, so the original `if self._cache:` guard caused the result to never be stored after the first fetch (because at that point the cache is empty). Fixed to `if self._cache is not None:` (same for the hit-check on the read path). The fix is backward-compatible and matches the developer's intent of distinguishing "not initialised" from "initialised but empty".

### `SessionsApiClient` HTTP method tests bypass `on_startup`

`on_startup` creates a real `httpx.AsyncClient`, complicating teardown. Tests for the HTTP methods use `started_api_client` which injects a pre-configured `AsyncMock` directly into `_client`, keeping the tests focused on URL construction, headers, and payload without lifecycle setup.
