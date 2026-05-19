# Unit Tests — `blueprint.agents.io`

Test coverage for `src/blueprint/agents/io/`.

---

## File overview

| File | Class under test | What is covered |
|---|---|---|
| `api/test_rest_api_base.py` | `RestApiBase` | HTTP verb decorators attach `_route`, `_wire_routes` registers routes, `_build_problem_details` RFC 7807 fields, `_resolve_status_title` |
| `api/actuators/test_actuator_api.py` | `ActuatorApi` | `_sanitize_config` (flat + nested), `liveness_probe` always UP, `on_startup`/`on_shutdown` lifecycle |
| `api/actuators/health/test_client_health.py` | `ClientHealthChecker` | `connect()` called before `health_check()`, healthy/unhealthy/mixed aggregation, empty client list |
| `api/actuators/health/test_health_cache.py` | `HealthCheckCache` | Initial state, provider updates, all-healthy→UP, one-unhealthy→DOWN, exception→unhealthy component, `get_cache_age_seconds`, `get_cache_info`, start/stop idempotency |
| `api/actuators/health/test_sessions_health.py` | `SessionsServiceHealthChecker` | REST API reachable→UP, `RequestError`→DOWN with details, fresh heartbeat→UP, stale heartbeat→DOWN, no heartbeat→UP (unknown), `update_heartbeat` |
| `api/eventing/test_event_handling_base.py` | `EventHandlingBase` | `_unwrap_nested_cloud_event` (via mixin) for non-dapr/dict/JSON-string/malformed-JSON/missing-fields/None data; `handle_event` PROCESSED→SUCCESS / other→RETRY |
| `api/eventing/test_dapr.py` | `DaprEventing` | `publish` PROCESSED→SUCCESS, no-handler→RETRY, `RetryableHandlerError`→RETRY, `InvalidEventError`→DROP, `CriticalHandlerError`→RETRY; `subscribe` returns empty dict |
| `api/eventing/test_nats.py` | `NatsEventing` | `subscribe`/`publish` delegate to `_client`, RuntimeError when client is None; `on_startup` fetches client, subscribes to handler-declared and config-declared topics, deduplicates, preserves handler-first order, skips when no topics; `_subscribe_to_topic` RuntimeError when client None, calls `_client.subscribe` with topic and callback |
| `api/eventing/test_sessions_bus.py` | `SessionsBus` | `on_startup` validation (no config/base_url/agent_id/api_key, already started, task created); `on_shutdown` (no task, running task cancelled); `_convert_to_cloud_event` (type/id/subject/source/data); `_process_job_notification` (no handler logged, `InvalidEventError`→cancel job, cancel failure swallowed, `RetryableHandlerError`→log, 403→invalidate+retry, 403 retry failure propagates `InvalidEventError`, non-403 propagates) |
| `api/scheduling/test_scheduler.py` | `SchedulerBase` | `_trigger_tick` calls `tick()`, returns `{"status": "triggered"}`, `on_shutdown` calls `shutdown(wait=True)`, `on_startup` registers trigger endpoint |
| `api/utilities/test_cache.py` | `CacheManagementApi` | 503 when no cache, `get_cache_stats`/`list_cache_namespaces`/`evict_cache_entry` delegate to registry cache service |
| `api/utilities/test_root.py` | `RootApi` | Service name/version/description from config (and defaults when `None`); both/one/neither doc links rendered; non-`APIRoute` routes skipped; `GET` route → direct link; non-`GET` route with `docs_url` → Swagger anchor link, without `docs_url` → plain path; route summary and sorted methods in row; cache hit skips config on second call |
| `telemetry/test_telemetry.py` | `TelemetryManager`, `TracingContext` | `configure_tracing` raises when config None, no-op when disabled, creates TracerProvider when enabled; `_build_exporters` OTLP/empty; `TracingContext` span lifecycle + attribute filtering |

---

## Fixtures

### `io/conftest.py`

| Fixture | Scope | Purpose |
|---|---|---|
| `reset_component_state` | function / **autouse** | Patches `CorrelationContextProvider`, resets `Component.shared_config` and `Component.shared_registry` after every test |
| `mock_config` | function | `MagicMock(spec=Config)` injected via `Component.configure`; available to all sub-packages |
| `mock_registry` | function | `MagicMock(spec=Registry)` stored in `Component.shared_registry`; prevents real Registry creation for tests that exercise registry-dependent paths |

### `io/api/eventing/conftest.py`

| Fixture | Scope | Purpose |
|---|---|---|
| `cloud_event` | function | Minimal valid `CloudEvent` for publish/handle tests |
| `processed_result` | function | `ProcessingResult` with `PROCESSED` status |
| `unhandled_result` | function | `ProcessingResult` with `NO_HANDLER_FOUND` status |
| `dapr_eventing` | function | `DaprEventing()` with `mock_registry` pre-set |
| `nats_eventing` | function | `NatsEventing()` with `mock_registry` pre-set |
| `connected_nats_eventing` | function | `nats_eventing` with `_client` pre-set to an async-capable mock |

---

## Decisions

### `spec=Registry` required for `mock_registry`

`_wire_routes` iterates over every class in `type(self).__mro__` and inspects each `__dict__` entry. When `Component.shared_registry = mock` stores the mock in `Component.__dict__['shared_registry']`, `_wire_routes` encounters it during iteration. A plain `MagicMock()` is callable and has `_route` (which returns an empty MagicMock, iterable as `[]`), causing `ValueError: not enough values to unpack (expected 3, got 0)`. Using `spec=Registry` constrains the mock to Registry's interface, so `hasattr(mock, '_route')` returns `False` and `_wire_routes` skips it.

### `ClientHealthChecker` and `HealthCheckCache` have no Component dependency

`ClientHealthChecker` takes `list[ClientBase]` directly, and `HealthCheckCache` is a standalone scheduler class. Neither inherits from `Component`. Their tests require no `mock_config`, `mock_registry`, or Component state setup. `reset_component_state` (autouse) is still present but is a no-op for these tests.

### `connected_nats_eventing` for NATS publish/subscribe tests

`NatsEventing.publish` and `subscribe` both guard with `if not self._client: raise RuntimeError(...)`. Pre-setting `_client` in a dedicated fixture keeps publish/subscribe tests focused on delegation behavior, separate from the `RuntimeError` guard tests.

### `liveness_probe` always returns UP — even with config errors

`ActuatorApi.liveness_probe` deliberately returns `status="UP"` even when `config.has_validation_errors()` is True. Tests assert this behavior explicitly to document that liveness ≠ readiness: pod restarts don't fix config errors, so staying live is intentional.

### `SessionsServiceHealthChecker` lives in `io/api/actuators/health/`, not `services/sessions/`

`SessionsServiceHealthChecker` implements `HealthCheckerBase` and carries no service logic — it is health-check infrastructure. The `services/` directory contains only `ServiceBase` subclasses. Moving it here co-locates it with `HealthCheckerBase` and `ClientHealthChecker`.

### `RootApi.root()` HTML is cached on the instance after the first call

Config values (`app_name`, `app_version`, `app_description`), `docs_url`/`redoc_url`, and `app.routes` are all fixed after application startup. The result is stored in `self._html_cache` on first call and returned directly on subsequent calls — confirmed by asserting `config.get` is not called after the cache is warm.

### `_build_problem_details` test avoids `"status"` key in dict detail

When `detail` is a dict, `_build_problem_details` copies it directly and then calls `int(problem["status"])`. Passing `{"status": "DOWN"}` would cause `ValueError`. Tests that verify dict detail pass-through use non-colliding keys (e.g. `"reason"`, `"errors"`).

### `SessionsBus` — exceptions raised inside `except` propagate outside all peer handlers

`_process_job_notification` has several `except` clauses at the same level. When `raise InvalidEventError(...)` is executed inside `except httpx.HTTPStatusError` (403 retry failure) or `raise` is executed (non-403), the new exception propagates **outside** the entire try/except block — Python does not route it to other `except` clauses at the same level. Tests for those two paths therefore use `pytest.raises` rather than asserting on side-effects inside the method.

### `SessionsBus.test_cancels_running_task` uses `asyncio.sleep` as the task body

In Python 3.11+, `Task.cancel()` on an unstarted task prevents the coroutine from ever executing, so a coroutine with an internal `cancelled.set()` handler will never set the flag. Using `asyncio.create_task(asyncio.sleep(999))` avoids this; checking `task.done()` after `on_shutdown()` is the reliable assertion.

### `_convert_to_cloud_event` requires `created_at` in test data

The `CloudEvent` model rejects `time=None`. `_convert_to_cloud_event` passes `time=job_data.get("created_at")`, which is `None` for data without that key. All `TestConvertToCloudEvent` test data includes `"created_at": "2024-01-01T00:00:00Z"` via `_job_data_with_time()`.
