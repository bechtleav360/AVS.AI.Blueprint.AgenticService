# Unit Tests — `blueprint.agents.handler`

Test coverage for `src/blueprint/agents/handler/`.

---

## File overview

| File | Class under test | What is covered |
|---|---|---|
| `test_event_handler_base.py` | `EventHandlerBase` | `__init__` stores default and custom priority; `can_handle` delegates to `can_handle_event` (True/False); `handle` passes through `HandlerResult`, `list[HandlerResult]`, dict, and `None` unchanged; `get_published_event_types` default returns `None`; `get_subscribed_topics` default returns `[]`; `__lt__` priority ordering and `sorted()` correctness |
| `test_handler_chain.py` | `HandlerChain` | `on_startup`/`on_shutdown` lifecycle no-ops; `process` with no handlers → `None`; declining handler skipped; accepting handler result returned; handler returning `None` passes to next; chain stops at first non-`None` result; handlers executed in ascending priority order; handler exception re-raised |

---

## Fixtures

### `handler/conftest.py`

| Fixture | Scope | Purpose |
|---|---|---|
| `reset_component_state` | function / **autouse** | Patches `CorrelationContextProvider`, resets `Component.shared_config` and `Component.shared_registry` after every test |
| `mock_config` | function | `MagicMock(spec=Config)` injected via `Component.configure` |
| `mock_registry` | function | `MagicMock(spec=Registry)` stored in `Component.shared_registry` |
| `cloud_event` | function | Minimal valid `GenericCloudEvent` for handler tests |

`StubHandler` is defined in `conftest.py` as a concrete `EventHandlerBase` subclass. It exposes `priority`, `can_handle`, and `result` constructor parameters so tests can configure each behaviour independently without additional fixtures.

---

## Decisions

### `StubHandler` defined in conftest, not in individual test files

Both `test_event_handler_base.py` and `test_handler_chain.py` need a concrete `EventHandlerBase` implementation. Defining `StubHandler` once in `conftest.py` avoids duplication. `HandlerChain` tests also define `OrderCapture` and `BrokenHandler` as local subclasses of `StubHandler` — they inherit the required `on_startup`/`on_shutdown` no-ops automatically.

### `HandlerChain.process` tested with real `StubHandler` instances, not mocks

`process` calls `sorted(registry.get_event_handler())`, which requires handlers to support `__lt__`. Plain `MagicMock` objects have non-deterministic `__lt__` behaviour. Using real `StubHandler` instances (with correct `EventHandlerBase.__lt__` semantics) makes the priority-ordering test meaningful and accurate.
