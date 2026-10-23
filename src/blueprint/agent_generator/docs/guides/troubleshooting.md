# Troubleshooting Guide

This guide covers common issues encountered when developing and deploying Blueprint Agents applications, along with their causes and solutions.

---

## Installation Issues

### Wrong Python Version

**Symptom:** Installation fails with an error referencing unsupported syntax or incompatible package versions.

```
ERROR: Package 'avs-blueprint-agents' requires a different Python: 3.10.x not in '>=3.13'
```

**Cause:** Blueprint Agents requires Python 3.13 or later.

**Solution:** Install the correct Python version and verify it is active:

```bash
python --version
# Must be 3.13 or later

# If using pyenv
pyenv install 3.13.0
pyenv local 3.13.0
```

### pip vs uv Installation

**Symptom:** Dependencies fail to resolve or installation is unexpectedly slow.

**Cause:** The standard `pip` resolver may struggle with complex dependency trees.

**Solution:** Use `uv` for faster and more reliable installs:

```bash
pip install uv
uv pip install avs-blueprint-agents
```

### TestPyPI Configuration

**Symptom:** Package not found when installing a pre-release version.

```
ERROR: Could not find a version that satisfies the requirement avs-blueprint-agents==0.6.0a3
```

**Cause:** Pre-release versions may be hosted on TestPyPI rather than the main PyPI index.

**Solution:** Configure pip to check TestPyPI as an additional index:

```bash
pip install avs-blueprint-agents==0.6.0a3 \
    --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/
```

---

## Configuration Errors

### ConfigError on Startup

**Symptom:** Application crashes immediately with a `ConfigError`.

```
blueprint.agents.config.config.ConfigError: Invalid app port: 70000
```

**Cause:** A setting failed validation at startup -- an `app_port` outside 1-65535, the `vllm`
provider without `model_api_key`, an agent settings file that cannot be parsed, an invalid
`envvar_prefix`. The message names the key or the file.

**Solution:** Correct the setting the message names. The framework's keys are **flat** keys under
`[default]`, not tables of their own:

```toml
[default]
app_name = "my-ai-service"
app_port = 8000
model_provider = "openai"
model_name = "gpt-4.1-mini"
```

Check which settings are required by running validation:

```bash
asbs validate
```

### Missing Required Settings

**Symptom:** A specific component fails to initialize because a setting it depends on is absent.

**Cause:** The component expects a configuration key that was not provided.

**Solution:** Check the component's documentation or source code for required settings. Use Dynaconf environment variable overrides if you cannot modify `settings.toml`:

```bash
export DYNACONF_MODEL_API_KEY="sk-..."
export DYNACONF_MODEL_PROVIDER="openai"
```

A top-level key takes one underscore after the prefix; `__` is nesting, so `DYNACONF_LLM__API_KEY`
would create an `llm.api_key` that nothing reads.

### Invalid Port Configuration

**Symptom:** Server fails to bind on startup.

```
[ERROR] Could not bind to port 80: Permission denied
```

**Cause:** The configured port is privileged (below 1024) or already in use.

**Solution:** Use a non-privileged port in `settings.toml`:

```toml
[default]
app_port = 8000
```

Or check for port conflicts:

```bash
lsof -i :8000
```

---

## Event Bus Connectivity

### Dapr Sidecar Not Running

**Symptom:** Application logs show errors when attempting to publish or subscribe to events.

```
ConnectionRefusedError: Cannot connect to Dapr sidecar at localhost:3500
```

**Cause:** The Dapr sidecar process is not running alongside the application.

**Solution:**

For local development, start the application via the Dapr CLI:

```bash
dapr run --app-id my-ai-service --app-port 8000 -- python -m uvicorn src.main:create_app --factory
```

In Kubernetes, verify the Dapr annotations are present on the pod:

```yaml
annotations:
  dapr.io/enabled: "true"
  dapr.io/app-id: "my-ai-service"
  dapr.io/app-port: "8000"
```

### NATS Connection Refused

**Symptom:** Event bus fails to connect to the NATS server.

```
nats.errors.ConnectionClosedError: connection refused
```

**Cause:** The NATS server is not reachable at the configured address.

**Solution:** Verify the NATS server is running and accessible:

```bash
# Check if NATS is running locally
nats-server --addr 0.0.0.0 --port 4222

# Test connectivity
nats sub test.subject
```

In Kubernetes, verify the NATS service is deployed and the Dapr component configuration points to the correct address.

**Refused against `localhost:4222` inside a pod?** The process is in development mode: `app_environment` is
unset or `"development"`, and `nats_url` is unset, so it fell back to localhost. The log says so twice -- a
WARNING that the service is running in development mode, and one naming the fallback. Set `app_environment`
and `nats_url` for the deployment. An image that sets only `DYNACONF_ENVIRONMENT` (the variable older
Dockerfiles used) stays in development: that variable selects nothing, and has to be renamed to
`DYNACONF_APP_ENVIRONMENT` (`<PREFIX>_APP_ENVIRONMENT` with your own `envvar_prefix`).

### `'nats_url' is not set` on Startup

**Symptom:** Startup fails, or one agent of a group is marked down, with:

```
ValueError: 'event_bus' is 'nats' but 'nats_url' is not set (app_environment is 'production'). ...
```

**Cause:** Outside development there is no default broker address.

**Solution:** Set `nats_url` in the group's `settings.toml`, or in the environment as the variable the message
names (`DYNACONF_NATS_URL` with the default prefix).

### `does not offer JetStream to this account`

**Symptom:** Startup fails, an agent is marked down, or the process shuts itself down, with:

```
JetStreamUnavailableError: Agent 'orders' declares 'nats_use_jetstream = true', but the NATS server at ... does not offer JetStream to this account
```

**Cause:** The agent is configured for JetStream and the server answered that JetStream is not
available -- not enabled on the server (`jetstream {}` missing from its configuration), or not
enabled for the account the connection authenticates as.

**Solution:** Enable JetStream for that server and account, or set `nats_use_jetstream = false`
if the agent is meant to run on Core NATS. The framework does not fall back on its own.

### `DurableConflictError`: a consumer that `belongs to another subscription`

**Symptom:** One agent never starts, or `/health/live` answers `503` naming it, and the log has a
CRITICAL line:

```
DurableConflictError: Agent 'orders': JetStream consumer 'orders-created-durable' on stream ... filters 'orders-created', not 'created', so it belongs to another subscription and is not bound. ... Not retried: ...
```

**Cause:** A durable of that name already exists on the stream for another subject. A root topic and
an agent's topic can derive one durable name -- root topic `orders-created` and agent `orders` on
topic `created` both give `orders-created-durable`. The framework never rebinds or rewrites a
consumer that filters another subject, and does not retry: the consumer keeps its filter until
someone changes it, so the start fails (in every agent, critical or not), or after startup liveness
goes DOWN.

**Solution:** Rename one of the two topics, or delete the consumer if it is stale.

### Other faults no retry can fix

**Symptom:** As above -- CRITICAL in the log, the start fails or `/health/live` answers `503` --
with `StreamConflictError`, `JetStreamPermissionError` or `TenancyError`.

**Cause and solution:** the message says which and what to change. `StreamConflictError`: the server
refused to create or widen the agent's stream, usually because another stream already captures one
of its subjects -- give the agent its own subjects or `nats_stream_name`. `JetStreamPermissionError`:
the account lacks a grant the agent needs to consume (the `$JS.API` requests, the deliver subjects) --
grant it. `TenancyError`: a named connection's login or deliver subject was refused by its broker --
correct the tenant's credentials or binding, or the account on the broker.

### Topic Mapping Mismatches

**Symptom:** Events are published but handlers never receive them.

**Cause:** The topic the handler subscribes to, or the event type it accepts, does not match what the
publisher sends.

**Solution:** Verify that topic and event type match exactly between publisher and subscriber:

```python
# Publisher (EventPublishingService)
await publisher.publish_event(event, topic="order.created")

# Handler -- the subscribed topic and the accepted type must match exactly
class OrderHandler(EventHandlerBase):
    def get_subscribed_topics(self) -> list[str]:
        return ["order.created"]

    async def can_handle_event(self, event, context) -> bool:
        return event.type == "order.created"
```

Check the Dapr subscription configuration to ensure topic mappings are correct.

---

## LLM Provider Issues

### Missing API Key

**Symptom:** Startup or the first agent call fails with an authentication error from the provider's
client, for the `openai` provider:

```
openai.OpenAIError: The api_key client option must be set either by passing api_key to the client or by setting the OPENAI_API_KEY environment variable
```

**Cause:** `model_api_key` is not configured.

**Solution:** Set it in `.secrets.toml` (for local development) or via an environment variable (for production):

```toml
# .secrets.toml (local only -- do not commit)
[default]
model_api_key = "YOUR_API_KEY_HERE"
```

```bash
# Environment variable
export DYNACONF_MODEL_API_KEY="YOUR_API_KEY_HERE"
```

### Invalid Model Name

**Symptom:** Agent initialization fails with a model-not-found error.

```
InvalidRequestError: The model 'gpt-5-turbo' does not exist
```

**Cause:** The configured model name is not recognized by the LLM provider.

**Solution:** Verify the model name against the provider's documentation:

```toml
[default]
model_provider = "openai"
model_name = "gpt-4.1-mini"  # Use a valid model identifier
```

### Timeout Errors

**Symptom:** LLM calls fail intermittently with timeout errors.

```
openai.APITimeoutError: Request timed out.
```

**Cause:** The LLM provider is taking longer than the configured timeout to respond. This is common with complex prompts or during high provider load.

**Solution:** Increase the timeout in configuration (unset, the provider SDK's own default applies):

```toml
[default]
model_timeout = 60  # seconds, per model request
```

Alternatively, consider breaking complex prompts into smaller steps or implementing retry logic in your service.

### Provider Not Supported

**Symptom:** Application raises an error about an unsupported LLM provider.

```
ValueError: Unsupported provider: 'anthropic'. Supported: ['vllm', 'openai']
```

**Cause:** `model_provider` names a provider the framework has no client for.

**Solution:** Use a supported provider name:

```toml
[default]
model_provider = "openai"   # OpenAI API
# model_provider = "vllm"   # a vLLM server at model_base_url; model_api_key is required
```

---

## Component Registration Errors

### Duplicate Component Names

**Symptom:** Application fails to start with a duplicate registration error.

```
ValueError: Component with name order_handler already exists
```

**Cause:** Two components resolve to the same registry name. A component is named after its class
(`OrderHandler` becomes `order_handler`) unless its `with_*` call passes `name=`, so registering one
class twice, or passing one `name=` twice, collides. In a group the message names the agent too.

**Solution:** Give the second registration a name of its own:

```python
agent = (
    AppBuilder()
    .with_service(PricingService)
    .with_service(PricingService, name="eu_pricing_service")  # a second instance, its own name
)
```

Run validation to detect duplicates:

```bash
asbs validate
```

### Looking Up Components in __init__

**Symptom:** A service fails when trying to access another service during construction.

```
ValueError: Component with name pricing_engine does not exist
```

**Cause:** The service is looking up a dependency before that dependency has been constructed and
registered. Components are constructed one by one in declaration order inside `build()`, so a
lookup in `__init__()` finds only the components declared before this one.

**Solution:** Access dependencies from the registry only within `on_startup()` or during request
handling, not in `__init__()`. The framework calls `on_startup()` after all components are
registered:

```python
class OrderService(ServiceBase):
    def __init__(self):
        super().__init__()
        self.pricing = None  # Do NOT look up other components here

    async def on_startup(self) -> None:
        # Safe -- all components are registered by this point
        self.pricing = self.registry.get_service("pricing_engine")
        self.cache = self.registry.get_cache()  # only if the agent declares .with_cache()

    async def on_shutdown(self) -> None:
        pass
```

---

## Health Check Failures

### Client Health Checker Failing

**Symptom:** The `/health/ready` endpoint returns unhealthy status for a specific client or external dependency.

```json
{
    "detail": {
        "status": "DOWN",
        "components": {
            "nats_client": {"status": "unhealthy", "message": "Unhealthy: ..."}
        }
    }
}
```

The probe answers `503`, and the payload is wrapped in `detail`.

**Cause:** The external service behind that entry is unreachable. The framework registers one entry
per client (named after the client), one per cache (`cache`, `cache:<name>`) and one per NATS client
with named connections (`<client>:connections`); in a group each is prefixed with the agent
(`orders.nats_client`).

**Solution:** Verify the external service is running and accessible from the application. Check
network policies and firewall rules in Kubernetes. The entry's `message` is the client's own report.

### Custom Health Checkers

**Symptom:** You need to add a health check for a custom dependency.

**Solution:** Implement a custom health checker and register it with the application:

```python
from blueprint.agents import AppBuilder
from blueprint.agents.io.api.actuators.health import HealthCheckerBase
from blueprint.agents.models.api import ComponentHealth


class DatabaseHealthChecker(HealthCheckerBase):
    def __init__(self, db):
        self._db = db

    async def health_check(self) -> ComponentHealth:
        try:
            await self._db.ping()
            return ComponentHealth(status="healthy", message="database reachable")
        except Exception as e:
            return ComponentHealth(status="unhealthy", message=str(e))


agent = AppBuilder().with_health_checker("database", DatabaseHealthChecker(db))
```

A check named like a built-in entry (`cache`, say) replaces it, with a WARNING; two of your own
checks under one name are refused at startup.

---

## Cache Issues

### Permission Errors on Cache Directory

**Symptom:** Startup fails because the cache directory cannot be created.

```
RuntimeError: Cache directory '.cache/blueprint' could not be created (Permission denied). ...
```

**Cause:** The application process does not have write permissions where the cache directory
(`cache.cache_dir`) is.

**Solution:** In Docker, create the directory at build time and hand it to the user the process runs
as, as the generated `Dockerfile` does:

```dockerfile
RUN mkdir -p /app/.cache && chown -R appuser:appuser /app/.cache
```

With a read-only root filesystem, mount an `emptyDir` volume there:

```yaml
volumes:
  - name: cache-volume
    emptyDir: {}
volumeMounts:
  - name: cache-volume
    mountPath: /app/.cache
```

### Disk Full

**Symptom:** Cache writes fail with a disk space error.

```
OSError: [Errno 28] No space left on device
```

**Cause:** The cache has grown beyond the available disk space.

**Solution:** Configure a cache size limit in `settings.toml`:

```toml
[default.cache]
size_limit = 500_000_000  # bytes; the default is 1 GB
default_ttl = 3600        # seconds an entry lives unless set() gives a ttl
```

In Kubernetes, set a size limit on the `emptyDir` volume:

```yaml
volumes:
  - name: cache-volume
    emptyDir:
      sizeLimit: 1Gi
```

### Stale Cache

**Symptom:** The application returns outdated data despite changes in the source.

**Cause:** Cached entries have not expired and are being served instead of fresh data.

**Solution:** Reduce the TTL or clear the cache manually:

```toml
[default.cache]
default_ttl = 300  # 5 minutes
```

To clear the cache programmatically (the cache API is synchronous):

```python
cache = self.registry.get_cache()
cache.clear()
```

---

## Testing Issues

### Async Test Setup

**Symptom:** Async tests fail with `RuntimeWarning: coroutine was never awaited` or `PytestUnraisableExceptionWarning`.

**Cause:** pytest is not configured to handle async test functions.

**Solution:** Install `pytest-asyncio` and set the mode to `auto` in `pyproject.toml`:

```bash
pip install pytest-asyncio
```

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

With `asyncio_mode = "auto"`, all async test functions are detected automatically. You do not need the `@pytest.mark.asyncio` decorator.

### Mock Registry Patterns

**Symptom:** Tests fail because the component cannot access services from the registry.

**Cause:** The registry was not mocked or injected into the component under test.

**Solution:** `registry` is a read-only property that reads the class-level shared registry, so
install the mock there before the component is constructed, and reset it afterwards:

```python
import pytest
from unittest.mock import MagicMock

from blueprint.agents.component.component import Component
from blueprint.agents.component.registry import Registry


@pytest.fixture
def mock_registry():
    registry = MagicMock(spec=Registry)
    mock_cache = MagicMock()  # the cache API is synchronous
    mock_cache.get.return_value = None
    registry.get_cache.return_value = mock_cache
    Component.shared_registry = registry
    yield registry
    Component.reset_shared_state()


@pytest.fixture
def my_service(mock_registry):
    from src.services.my_service import MyService
    return MyService()
```

### Missing pytest-asyncio

**Symptom:** Tests are collected but skipped or produce warnings about missing async support.

```
PytestUnhandledCoroutineWarning: async def functions are not natively supported
```

**Cause:** The `pytest-asyncio` package is not installed.

**Solution:**

```bash
pip install pytest-asyncio
```

Verify it is listed in your test dependencies in `pyproject.toml`:

```toml
[project.optional-dependencies]
test = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
    "pytest-mock>=3.10",
    "httpx>=0.24",
]
```
