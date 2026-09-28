---
name: blueprint-testing
description: Testing a Blueprint Agents service - mock registries, unit tests for handlers, services, APIs and agents, integration tests, and the pytest-asyncio setup. Use when writing or fixing tests for any Blueprint component.
user-invocable: true
---

# Testing Blueprint Components

```bash
asbs docs guides/testing --cat     # mock registry, per-component patterns, integration tests
```

The guide covers, in order: Test Setup, Creating a Mock Registry, Unit Testing Components,
Integration Testing, Running Tests, Tips and Best Practices. **Read *Creating a Mock Registry*
before writing the first test** - components resolve their dependencies through `self.registry`, so
a test that does not provide one tests nothing.

## Conventions

| Thing | Convention |
|---|---|
| File | `test_<module>.py` |
| Class | `Test<Component>` |
| Method | `test_<behavior>_<expected>` |
| Shared fixtures | `conftest.py` |
| Async | `asyncio_mode = auto` - no `@pytest.mark.asyncio` needed |

- `MagicMock(spec=...)` for synchronous dependencies, `AsyncMock()` for async ones. The `spec` is
  what makes a renamed method fail the test instead of passing silently.
- **`assert` is for tests only.** It is not permitted in production code in this framework.

## The lifecycle trap

Components do not have `self.registry` or `self.config` until after construction, and they resolve
dependencies in `on_startup()`. So a unit test must **call `on_startup()` itself** after attaching
the mock registry - constructing the component is not enough, and a test that skips it will fail on
an attribute that production code sets correctly.

Schedulers additionally require `await super().on_startup()` inside any overridden `on_startup`; the
base class is what starts the timer and registers the trigger route.

## Running

```bash
pytest tests/                     # everything
pytest tests/unit -v --tb=short   # what CI runs on publish
```

Test dependencies live in the `ci` extra: `pip install -e ".[ci]"`.
