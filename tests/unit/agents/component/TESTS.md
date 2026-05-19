# Unit Tests — `blueprint.agents.component`

Test coverage for `src/blueprint/agents/component/component.py` and
`src/blueprint/agents/component/registry.py`.

---

## File overview

| File | Class under test | What is covered |
|---|---|---|
| `test_component.py` | `Component`, `_ComponentMeta` | `configure`, `init_registry`, `__init__`, properties, `name` setter |
| `test_component.py` | `_is_cloud_event`, `_stamp_span` | Helper function correctness |
| `test_component.py` | `traced` decorator | Async/sync span creation, error status, CloudEvent/plain-value stamping |
| `test_registry.py` | `Registry` | Construction, add/get/has/rename/clear, type-based lookups, `cache_service` |

---

## Fixtures (`conftest.py`)

| Fixture | Scope | Purpose |
|---|---|---|
| `ConcreteComponent` | — (class) | Minimal concrete `Component` subclass with no-op lifecycle hooks, used across both test files |
| `concrete_component` | function | Returns a `ConcreteComponent` instance |
| `reset_component_state` | function / **autouse** | Resets `Component.shared_config` and `Component.shared_registry` to `None` after every test; also patches `CorrelationContextProvider` during the test |

---

## Decisions

### `reset_component_state` autouse fixture
`_ComponentMeta` stores `shared_config` and `shared_registry` as class-level
attributes on `Component`. Without cleanup, the first test that sets these values
would leak state into all subsequent tests, causing spurious failures (e.g.
`configure()` raising "already set" on the second call). The autouse fixture
resets both attributes to `None` after every test regardless of outcome.

### Patching `CorrelationContextProvider` in `reset_component_state`
The registry calls `CorrelationContextProvider.get_correlation_context()` during
component registration. Patching it with a `MagicMock` prevents any real
correlation-context side effects from being triggered by tests that are not
concerned with logging.

### Module-scoped OTel provider in `test_component.py`
The OpenTelemetry SDK does not allow replacing the global tracer provider after
first initialisation — a second call is silently ignored. A single `_otel_provider`
fixture with `scope="module"` initialises the SDK once for the entire module and
shares the same `InMemorySpanExporter` across all `traced()` tests. A
function-scoped `span_exporter` fixture clears the exporter before and after each
test to prevent span bleed-over between tests.

### `registry` fixture and stub classes kept local to `test_registry.py`
`Registry` takes a base class as its constructor argument. The `StubBase`,
`StubA`, and `StubB` classes and the `registry` fixture are only needed inside
`test_registry.py` and carry no meaning outside it. Keeping them module-local
avoids polluting the shared conftest with types that have no reuse value.
