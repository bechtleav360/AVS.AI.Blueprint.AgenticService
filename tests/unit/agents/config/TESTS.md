# Unit Tests — `blueprint.agents.config`

Test coverage for `src/blueprint/agents/config/config.py` and
`src/blueprint/agents/config/custom_logging.py`.

---

## File overview

| File | Class under test | What is covered |
|---|---|---|
| `test_config_api_key_resolution.py` | `Config` | Global vs. runtime-specific API key loading (pre-existing, refactored) |
| `test_config_init.py` | `Config` | `__init__`, `get`, `get_package_root`, `_process_dynabox` |
| `test_config_validation.py` | `Config` | `validate`, `has_validation_errors`, `get_validation_errors` |
| `test_config_get_ai_config.py` | `Config` | `get_ai_config` — global/runtime fallback chain, `UsageLimits` |
| `test_config_get_runtime_config.py` | `Config` | `get_runtime_config` — merging, key normalisation |
| `test_config_specialized_configs.py` | `Config` | `get_prompt_config`, `get_observability_config`, `get_cache_config`, `get_event_publishing_config`, `get_nats_subscription_config` (absent→`[]`, list→topics, non-list→`[]`+warning, falsy entries filtered) |
| `test_health_check_filter.py` | `HealthCheckFilter` | All filter/pass branches for health-check log records |
| `test_correlation_context.py` | `CorrelationContext`, `CorrelationContextProvider` | set/get/reset, filter injection, singleton behaviour |
| `test_logging_manager.py` | `LoggingManager` | configure (idempotency, filter attachment), format strings, noisy suppression, `set_level` |

---

## Fixtures (`conftest.py`)

| Fixture | Scope | Purpose |
|---|---|---|
| `base_settings_file` | function | Path to `fixtures/settings_base.toml` — minimal valid config |
| `api_key_settings_file` | function | Path to `fixtures/settings_api_key_test.toml` — multi-runtime API key scenarios |
| `write_settings` | function | Factory: writes arbitrary TOML text to `tmp_path`, returns the `Path` |
| `base_config` | function | `Config` instance loaded from `settings_base.toml` |
| `mock_logging_configure` | function / **autouse** | Patches `LoggingManager` in `config.py` to prevent global logging side effects |

### Fixture files

| File | Used by |
|---|---|
| `fixtures/settings_base.toml` | `base_config` fixture and most `Config` tests |
| `fixtures/settings_api_key_test.toml` | API key resolution and runtime override tests |

---

## Decisions

### `write_settings` instead of per-scenario TOML files
Most scenarios need only small variations from a valid base config (a different
port, a missing key, an extra section). Rather than creating a TOML file per
scenario, a `write_settings` factory fixture writes TOML text to pytest's
`tmp_path` on demand. This keeps test intent self-contained and avoids fixture
file proliferation. Shared, reused configs (`settings_base.toml`,
`settings_api_key_test.toml`) remain as real files.

### `mock_logging_configure` autouse fixture
`Config.__init__` unconditionally calls `LoggingManager.configure()`, which
touches global `logging` state (root logger handlers, third-party logger levels).
Without isolation this would pollute every test that constructs a `Config`.
The autouse fixture patches `LoggingManager` at the point of use inside
`config.py` for all tests in this directory, except for `test_logging_manager`
(detected via `request.node.nodeid`), which exercises `LoggingManager` directly
and needs real behaviour. This mirrors the `mock_prompt_loader` pattern already
used in `tests/unit/agents/conftest.py`.

### Grouping specialised config getters in one file
`get_prompt_config`, `get_observability_config`, `get_cache_config`, and
`get_event_publishing_config` each construct a Pydantic model directly from
settings with minimal logic. Splitting them into four files would add overhead
without improving clarity. They are grouped in
`test_config_specialized_configs.py` by test class, one class per method.

### `LoggingManager` test isolation (`restore_loggers` autouse)
`LoggingManager` methods write to global logger instances (`logging.getLogger()`),
which persist across tests. An autouse `restore_loggers` fixture inside
`TestLoggingManager` snapshots and restores the root logger, `uvicorn.access`,
and all noisy loggers after each test, preventing cross-test contamination without
requiring mocks that would defeat the purpose of these tests.

### `ContextVar.reset()` semantics
`ContextVar.reset(token)` restores the variable to the state it held **before**
the `set()` call that produced the token — not to the value of that `set()` call.
The initial test captured the token from `set("first")`, then expected the value
to return to `"first"` after reset — which is incorrect. The fix captures the
token from `set("second")` instead, so reset returns the variable to `"first"`.
