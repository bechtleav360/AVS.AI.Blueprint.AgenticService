# Unit Tests — `blueprint.agents.agent`

Test coverage for `src/blueprint/agents/agent/`.

---

## File overview

| File | Class under test | What is covered |
|---|---|---|
| `test_metrics_extractor.py` | `MetricsExtractor` | `extract_response_text`: `.data` present, `.output` fallback, `str()` fallback; `extract_usage_info`: all attrs, partial attrs, `usage()` returns None, `usage()` raises, no attribute, non-callable attribute |
| `test_metrics_recorder.py` | `MetricsRecorder` | `record`: usage logged, warning when no usage, OTel skipped when disabled, OTel counter+histogram created when enabled+meter provided, no OTel when meter is None, config exception suppressed |
| `test_agent_builder.py` | `AgentBuilder` | `with_model_from_config` (no model name/provider/unsupported provider → ValueError, success stores config, deprecated `runtime_name` warns); fluent setters store correct state; `get_model_settings` (max\_tokens, temperature, absent → empty dict); `build()` error paths (no model → ValueError, already built → RuntimeError, conflicting kwarg → ValueError, unknown kwarg → ValueError, no system prompt → ValueError) |
| `test_agent_runtime.py` | `AgentRuntime` | `get_pydantic_name` (name and None); `get_model_settings` (cache hit, max\_tokens, temperature, exception → `{}`, caches after first call); `get_prompt` (cache hit, cache miss with caching, FileNotFoundError propagated); `record_metrics` (recorder None → no-op, explicit model name, resolved from `.model.model_name`, fallback to "unknown"); `on_startup` (no client → no-op, client set → `model = client.create_model()`); `run_with_prompt`/`run_with_prompt_sync` → NotImplementedError |
| `test_prompt_loader.py` | `PromptLoader` | (pre-existing — 6 tests) |

---

## Fixtures

### `agent/conftest.py`

| Fixture | Scope | Purpose |
|---|---|---|
| `reset_component_state` | function / **autouse** | Patches `CorrelationContextProvider`, resets `Component.shared_config` and `Component.shared_registry` after every test |
| `mock_config` | function | `MagicMock(spec=Config)` injected via `Component.configure` |
| `mock_registry` | function | `MagicMock(spec=Registry)` stored in `Component.shared_registry` |
| `runtime` | function | `AgentRuntime` created via `object.__new__` with instance attributes set directly (see decision below) |

---

## Decisions

### `AgentRuntime` instantiated via `object.__new__`

`AgentRuntime.__init__` calls both `pydantic_ai.Agent.__init__` (requires model, registers context vars) and `Component.__init__` (accesses registry). Bypassing both with `object.__new__` and manually setting `_name`, `_ai_client`, `_prompt_cache`, `_model_settings`, `_recorder` isolates the methods under test from framework init side-effects.

### `runtime` fixture must set `_override_name` ContextVar

`pydantic_ai.Agent.name` reads `self._override_name.get()` without a default — this raises `LookupError` if the ContextVar is unset. The fixture creates the ContextVar and calls `.set(None)` so the property falls back to `self._name` without raising.

### `AgentBuilder.build()` success path is not tested

`build()` creates an AI client Component (VLLMClient/OpenAIClient — each with their own registry side-effects) and then calls `AgentRuntime.__init__` via multiple inheritance. Exercising the full path would require mocking pydantic_ai's `Agent.__init__` and at least one AI client constructor — integration territory. Error paths are fully covered; the success path belongs in integration tests.

### `AgentBuilder` tests do not need `mock_registry` for error-path tests

`AgentBuilder` does not inherit from `Component`, so its constructor and fluent setters never access `Component.shared_registry`. `mock_registry` is only required in `build()` tests where the patched `_CLIENT_MAP` constructor might reach Component registration code; it is declared there explicitly rather than in a shared fixture.

### Top-level `tests/unit/agents/conftest.py` autouse fixture is already in effect

The parent conftest mocks `blueprint.agents.agent.agent_builder.PromptLoader.load_prompt` for all tests except those listed in `skip_nodes`. Builder tests that exercise `build()` error paths raised before the prompt-loading call are unaffected whether or not the mock is applied.
