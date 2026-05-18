# Unit Tests — `blueprint.agents.clients`

Test coverage for `src/blueprint/agents/clients/`.

---

## File overview

| File | Class under test | What is covered |
|---|---|---|
| `test_client_base.py` | `ClientBase` | `on_startup`/`on_shutdown` lifecycle, `_get_connected_client` lazy-connect logic, `client` property |
| `ai/test_ai_client_base.py` | `AIClientBase` | `__init__` runtime name storage, component renaming, `_model` initialisation |
| `ai/test_openai_client.py` | `OpenAIClient` | `_is_connected`, `connect` (no-op), `close`, `subscribe`/`publish` (no-ops), `create_model`, `health_check` |
| `ai/test_vllm_client.py` | `VLLMClient` | Same shape as OpenAI; additionally verifies `base_url`/`api_key` forwarding to `AsyncOpenAI` |
| `io/test_dapr_client.py` | `DaprClient` | `_is_connected`, `connect`/`close`, `subscribe` (no-op), `publish` (URL, headers, routing key, pubsub name), `health_check` |
| `io/test_nats_client.py` | `NATSClient` | `__init__` defaults, `_is_connected` variants, `connect` (Core + JetStream), `close`, `publish`, `health_check` |

`IOClientBase` has no logic and has no test file.

---

## Fixtures

### `clients/conftest.py`

| Fixture | Scope | Purpose |
|---|---|---|
| `reset_component_state` | function / **autouse** | Patches `CorrelationContextProvider`, resets `Component.shared_config` and `Component.shared_registry` after every test |
| `mock_config` | function | `MagicMock(spec=Config)` injected via `Component.configure`; available to all sub-packages |

### `clients/ai/conftest.py`

| Fixture | Scope | Purpose |
|---|---|---|
| `mock_ai_config` | function | Real `AIConfig` instance with test values; shared by OpenAI and VLLM tests |
| `openai_client` | function | `OpenAIClient("test_runtime")` with `mock_config.get_ai_config` pre-wired |
| `vllm_client` | function | `VLLMClient("test_runtime")` with `mock_config.get_ai_config` pre-wired |
| `patch_openai_deps` | function | Context-manager patches for `AsyncOpenAI`, `OpenAIProvider`, `OpenAIResponsesModel`, `OpenAIResponsesModelSettings` |
| `patch_vllm_deps` | function | Context-manager patches for `AsyncOpenAI`, `OpenAIProvider`, `OpenAIChatModel` |

### `clients/io/conftest.py`

| Fixture | Scope | Purpose |
|---|---|---|
| `cloud_event` | function | Minimal real `CloudEvent` instance; `dict(event)` works natively |
| `dapr_client` | function | `DaprClient` with `mock_config.get` returning test Dapr config values |
| `mock_httpx_client` | function | Async-mock `httpx.AsyncClient` with `post`/`get`/`aclose` |
| `connected_dapr_client` | function | `dapr_client` with `_client` pre-set to `mock_httpx_client` |
| `nats_client` | function | `NATSClient` with `mock_config.get` returning test NATS config values |
| `mock_nats_core` | function | Mock NATS client (Core mode, no JetStream) |
| `mock_nats_jetstream` | function | `(mock_nats_client, mock_js)` tuple with JetStream enabled |
| `connected_nats_client` | function | `nats_client` with `_nats_client` and `_client` pre-set to `mock_nats_core` |

---

## Decisions

### `mock_config` at the `clients/` level
Every client class resolves configuration through `Component.shared_config`. A
single `mock_config` fixture in the top-level conftest sets this once and is
inherited by all sub-packages, avoiding repetition in `ai/` and `io/` conftest
files.

### `reset_component_state` mirrors the component conftest
`_ComponentMeta` stores `shared_config` and `shared_registry` as class-level
attributes. The same autouse reset pattern from `component/conftest.py` is
applied here for the same reason: without cleanup, the first test to call
`Component.configure()` would cause every subsequent test to raise "already set".

### `connected_*_client` fixtures for IO publish/health tests
`DaprClient.publish()` and `NATSClient.publish()` both call `await self.client`
which triggers `_get_connected_client()`. Pre-setting `_client` (and
`_nats_client` for NATS) in a dedicated fixture means transport-level tests stay
focused on publish/subscribe logic and are not accidentally testing `connect()` as
a side effect.

### SDK constructors patched at the conftest level, not per-test
`create_model()` constructs three to four SDK objects (`AsyncOpenAI`,
`OpenAIProvider`, model class, settings class). Patching all of them in every
test method would be repetitive. A single `patch_openai_deps` / `patch_vllm_deps`
fixture patches the whole group and yields a dict of mocks for assertions.

### Real `CloudEvent` instances for publish tests
`DaprClient.publish()` and `NATSClient.publish()` call `json.dumps(dict(event))`.
`CloudEvent` is a Pydantic model that implements `__iter__` to yield field pairs,
so `dict(event)` works natively and produces a JSON-serialisable dict. Using a
real instance avoids mock iteration issues and keeps the assertion on the actual
serialised payload meaningful.
