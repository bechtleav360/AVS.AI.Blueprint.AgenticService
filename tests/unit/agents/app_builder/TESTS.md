# Unit Tests — `blueprint.agents.app_builder`

Test coverage for `src/blueprint/agents/app_builder.py`.

---

## File overview

| File | Class under test | What is covered |
|---|---|---|
| `test_app_builder.py` | `AppBuilder` | `with_handler` (TypeError for non-subclass, class instantiated, instance accepted without re-instantiation, name propagated, returns self); `with_service`/`with_agent`/`with_scheduler`/`with_rest_api` (instance accepted, returns self); `with_cache` (enabled creates DiskCacheService, disabled skips config read); `with_health_checker` (stored pending before build, added immediately after build, multiple checkers accumulated, returns self); `build()` (event_bus=dapr/nats/unknown/no-handlers routing, EventPublishingService conditional on IO clients, pending health checkers wired, returns FastAPI instance) |

---

## Fixtures

### `app_builder/conftest.py`

| Fixture | Scope | Purpose |
|---|---|---|
| `reset_component_state` | function / **autouse** | Patches `CorrelationContextProvider`, resets `Component.shared_config` and `Component.shared_registry` after every test |
| `mock_config` | function | `MagicMock(spec=Config)` injected via `Component.configure` |
| `mock_registry` | function | `MagicMock(spec=Registry)` stored in `Component.shared_registry` |
| `builder` | function | `AppBuilder(mock_config)` — for fluent-setter tests where shared_config is pre-set |
| `build_config` | function | `MagicMock(spec=Config)` NOT injected — `build()` injects it itself |
| `builder_for_build` | function | `AppBuilder(build_config)` with `mock_registry` active but `shared_config = None` |
| `all_build_mocks` | function | Context-managed set of patches for every Component constructor and FastAPI that `build()` creates; yields a `SimpleNamespace` of the individual mocks |

`wire_empty_registry(mock_registry)` is a helper (not a fixture) that sets all registry collection methods to return empty lists, giving `build()` tests a clean baseline to override selectively.

`StubHandler` is defined in `conftest.py` as a minimal concrete `EventHandlerBase` for tests that need to pass a real handler type to `with_handler`.

---

## Decisions

### Two separate builder fixtures for setter vs. build tests

`mock_config` calls `Component.configure(config)`. `build()` also calls `Component.configure(self._config)` — the metaclass guard raises `RuntimeError` if called twice. Fluent-setter tests use `builder` (which depends on `mock_config`); `build()` tests use `builder_for_build` (which uses `build_config` that bypasses `Component.configure` until `build()` is called).

### `build()` tests patch every constructor that `build()` calls

`build()` instantiates `DaprClient`, `DaprEventing`, `NATSClient`, `NatsEventing`, `EventProcessingService`, `EventPublishingService`, `ActuatorApi`, `RootApi`, `CacheManagementApi`, and `FastAPI`. Each creates a real Component or FastAPI object with its own registry and file-system side-effects. All are patched via the `all_build_mocks` fixture so tests can assert on call counts without triggering infrastructure setup.

### `_create_lifespan_manager` and `_build_rest_endpoints` are not tested

`_create_lifespan_manager` is a pure integration concern — it orchestrates startup/shutdown of every registered component in dependency order. `_build_rest_endpoints` wires routers that belong to mocked components; verifying it would test FastAPI's routing machinery rather than production logic. Both are covered by integration tests.

### `with_cache` disabled test asserts on config access, not registry state

`MagicMock(spec=Registry)` pre-creates a `cache_service` attribute (because `Registry` declares it), so comparing the attribute to `None` after `with_cache(enabled=False)` always fails. The meaningful invariant is that the config is not consulted and no DiskCacheService is constructed, which is captured by asserting `mock_config.get_cache_config.assert_not_called()`.
