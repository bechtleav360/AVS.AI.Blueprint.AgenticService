# Unit Tests — `blueprint.agents.app_builder`

Test coverage for `src/blueprint/agents/app_builder.py`.

---

## File overview

| File | Class under test | What is covered |
|---|---|---|
| `test_deferred_wiring.py` | `AppBuilder`, `Declaration` | Nothing is constructed or registered before `build()`; what a declaration records (kind, target, name, ambient namespace, kwargs); the declaration-order refusal and the three cases it must *not* fire on; where the configuration may be handed over and the refusal when it is given twice; the single-use guard; an application that declares nothing; an unbuilt `AgentBuilder` handed to `with_agent` and built with its agent's scoped view |
| `test_namespace_placement.py` | `AppBuilder`, `namespace_scope`, `host_agent` | A component reaches the right agent without anyone naming a namespace: the ambient scope qualifies the registry name, reaches the component and is never forwarded to its constructor; it is captured at the call, not at construction; explicit names are qualified too; an already-built instance is refused for another namespace; `host_agent` records the composition and refuses a duplicate, the root and an illegal name; and the four deleted surfaces (`AgentRegistration`, `RegisteredComponent`, `NamespaceBuilder`, `with_namespace`/`with_registration`) stay deleted |
| `test_declaration_surface.py` | `AppBuilder`, `Declaration.replay` | The gate that keeps the declaration API and the group's replay in agreement: every public `with_*` is discovered rather than listed (a new one fails the file until it has a sample call), and per method -- one declaration recorded, the registry untouched, `replay` onto a fresh builder reproducing the declaration exactly, a replay inside `namespace_scope` taking the namespace from the scope, and the recorded `kind` having a `with_<kind>` to replay onto; plus the irregular positional name of `with_health_checker` surviving a replay |
| `test_app_builder.py` | `AppBuilder` | `with_handler` (TypeError for non-subclass, class instantiated, instance accepted without re-instantiation, name propagated, returns self); `with_service`/`with_agent`/`with_scheduler`/`with_rest_api` (instance accepted, returns self); `with_cache` (enabled creates DiskCacheService, disabled skips config read); `with_health_checker` (recorded as a `Declaration` before build, added straight to the actuator after build, several accumulate, a checker is never constructed, returns self); `build()` (event_bus=dapr/nats/unknown/no-handlers routing, EventPublishingService conditional on IO clients, pending health checkers wired, returns FastAPI instance); scheduler wiring (an event-mode scheduler is wired before the transport decision, so its tick handler is what causes a NATS client and eventing endpoint to be created; an in-process scheduler alone creates neither); the publish/consume split (`event_publishing_enabled` off means no client; on means a client with no eventing component and no `EventProcessingService`; the string form an environment variable delivers; rejections for no transport, `"sessions"` and a non-boolean; and a consuming application still publishing without the key) |

---

## Fixtures

### `app_builder/conftest.py`

| Fixture | Scope | Purpose |
|---|---|---|
| `reset_component_state` | function / **autouse** | Patches `CorrelationContextProvider`, then calls `Component.reset_shared_state()` after every test |
| `mock_config` | function | `MagicMock(spec=Config)` injected via `Component.configure` |
| `mock_registry` | function | `MagicMock(spec=Registry)` stored in `Component.shared_registry` |
| `builder` | function | `AppBuilder(mock_config)` — for fluent-setter tests where shared_config is pre-set |
| `build_config` | function | `MagicMock(spec=Config)` NOT injected — `build()` injects it itself |
| `builder_for_build` | function | `AppBuilder(build_config)` with `mock_registry` active but `shared_config = None` |
| `all_build_mocks` | function | Context-managed set of patches for every Component constructor and FastAPI that `build()` creates; yields a `SimpleNamespace` of the individual mocks |

`wire_empty_registry(mock_registry)` is a helper (not a fixture) that sets all registry collection methods to return empty lists, giving `build()` tests a clean baseline to override selectively.

`StubHandler` is defined in `conftest.py` as a minimal concrete `EventHandlerBase` for tests that need to pass a real handler type to `with_handler`.

`realize(builder)` is a helper (not a fixture) that runs `build()`'s own replay pass on its own. A `with_*()` call records rather than constructs, so a test asserting on the registry has to say when construction happens; `build()` would do it but also creates the actuator, the root API and a FastAPI application, which would drown the one or two components the test is about.

**Group assembly is tested in `tests/unit/agents/test_agent_group.py`**, not here: collection is `AgentGroup`'s job and an `AppBuilder` never learns it can be collected.

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
