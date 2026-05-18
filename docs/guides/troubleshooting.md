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

**Symptom:** Application crashes immediately with a `ConfigError` or `ValidationError`.

```
blueprint.agents.exceptions.ConfigError: Missing required configuration: 'app.name'
```

**Cause:** Required settings are missing from `settings.toml` or have not been provided via environment variables.

**Solution:** Verify that `settings.toml` contains all required keys:

```toml
[app]
name = "my-ai-service"
port = 8000

[llm]
provider = "openai"
model = "gpt-4"
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
export DYNACONF_LLM__API_KEY="sk-..."
export DYNACONF_LLM__PROVIDER="openai"
```

### Invalid Port Configuration

**Symptom:** Server fails to bind on startup.

```
[ERROR] Could not bind to port 80: Permission denied
```

**Cause:** The configured port is privileged (below 1024) or already in use.

**Solution:** Use a non-privileged port in `settings.toml`:

```toml
[app]
port = 8000
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
dapr run --app-id my-ai-service --app-port 8000 -- python -m uvicorn src.main:app
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

### Topic Mapping Mismatches

**Symptom:** Events are published but handlers never receive them.

**Cause:** The topic name in the handler's `event_type` does not match the topic used by the publisher.

**Solution:** Verify that the event types match exactly between publisher and subscriber:

```python
# Publisher
await event_bus.publish(topic="order.created", data=order_data)

# Handler -- event_type must match exactly
class OrderHandler(EventHandlerBase):
    event_type = "order.created"  # Must match the publish topic
```

Check the Dapr subscription configuration to ensure topic mappings are correct.

---

## LLM Provider Issues

### Missing API Key

**Symptom:** Agent calls fail with an authentication error.

```
AuthenticationError: No API key provided. Set DYNACONF_LLM__API_KEY or add it to secrets.toml.
```

**Cause:** The LLM provider API key is not configured.

**Solution:** Set the API key in `secrets.toml` (for local development) or via an environment variable (for production):

```toml
# secrets.toml (local only -- do not commit)
[llm]
api_key = "sk-..."
```

```bash
# Environment variable
export DYNACONF_LLM__API_KEY="sk-..."
```

### Invalid Model Name

**Symptom:** Agent initialization fails with a model-not-found error.

```
InvalidRequestError: The model 'gpt-5-turbo' does not exist
```

**Cause:** The configured model name is not recognized by the LLM provider.

**Solution:** Verify the model name against the provider's documentation:

```toml
[llm]
provider = "openai"
model = "gpt-4"  # Use a valid model identifier
```

### Timeout Errors

**Symptom:** LLM calls fail intermittently with timeout errors.

```
TimeoutError: Request timed out after 30.0 seconds
```

**Cause:** The LLM provider is taking longer than the configured timeout to respond. This is common with complex prompts or during high provider load.

**Solution:** Increase the timeout in configuration:

```toml
[llm]
timeout = 60  # seconds
```

Alternatively, consider breaking complex prompts into smaller steps or implementing retry logic in your service.

### Provider Not Supported

**Symptom:** Application raises an error about an unsupported LLM provider.

```
ValueError: LLM provider 'anthropic_legacy' is not supported
```

**Cause:** The provider name in configuration does not match any registered provider.

**Solution:** Use a supported provider name:

```toml
[llm]
provider = "openai"     # OpenAI API
# provider = "azure"    # Azure OpenAI
# provider = "anthropic" # Anthropic Claude
```

---

## Component Registration Errors

### Duplicate Component Names

**Symptom:** Application fails to start with a duplicate registration error.

```
RegistrationError: Component 'order_handler' is already registered
```

**Cause:** Two components share the same `name` attribute.

**Solution:** Ensure every component has a unique `name`:

```python
class OrderCreatedHandler(EventHandlerBase):
    name = "order_created_handler"  # Must be unique

class OrderUpdatedHandler(EventHandlerBase):
    name = "order_updated_handler"  # Must be unique
```

Run validation to detect duplicates:

```bash
asbs validate
```

### Missing Dependencies in on_startup

**Symptom:** A service raises a `KeyError` or `None` reference when trying to access another service during startup.

```
KeyError: 'pricing_engine'
```

**Cause:** The service is trying to access a dependency from the registry before that dependency has been registered and started.

**Solution:** Access dependencies from the registry only within `on_startup()` or during request handling, not in `__init__()`. The framework calls `on_startup()` after all components are registered:

```python
class OrderService(ServiceBase):
    name = "order_service"

    async def on_startup(self) -> None:
        # Safe -- all components are registered by this point
        self.pricing = self.registry.get_service("pricing_engine")
```

### Accessing Registry in __init__

**Symptom:** `AttributeError: 'NoneType' object has no attribute 'get_service'` during component construction.

**Cause:** The registry is not available during `__init__()`. It is injected after construction.

**Solution:** Move all registry access to `on_startup()`:

```python
class MyService(ServiceBase):
    name = "my_service"

    def __init__(self):
        # Do NOT access self.registry here -- it is not set yet
        self._client = None

    async def on_startup(self) -> None:
        # Registry is available here
        cache = self.registry.get_service("cache")
        self._client = await self._create_client()
```

---

## Health Check Failures

### Client Health Checker Failing

**Symptom:** The `/health/ready` endpoint returns unhealthy status for a specific client or external dependency.

```json
{
    "status": "unhealthy",
    "components": {
        "llm_provider": {"status": "unhealthy", "error": "Connection refused"}
    }
}
```

**Cause:** The external service that the health checker is testing is unreachable.

**Solution:** Verify the external service is running and accessible from the application. Check network policies and firewall rules in Kubernetes. Review the health checker configuration:

```python
# Verify the health check endpoint is correct
health_checker = ClientHealthChecker(
    name="llm_provider",
    url="https://api.openai.com/v1/models",
    timeout=5
)
```

### Custom Health Checkers

**Symptom:** You need to add a health check for a custom dependency.

**Solution:** Implement a custom health checker and register it with the application:

```python
from blueprint.agents.health import HealthCheckerBase


class DatabaseHealthChecker(HealthCheckerBase):
    name = "database"

    async def check(self) -> dict:
        try:
            await self.db.ping()
            return {"status": "healthy"}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
```

---

## Cache Issues

### Permission Errors on Cache Directory

**Symptom:** Cache operations fail with permission errors.

```
PermissionError: [Errno 13] Permission denied: '/app/.cache/data.db'
```

**Cause:** The application process does not have write permissions to the cache directory.

**Solution:** In Docker, ensure the cache directory is writable:

```dockerfile
RUN mkdir -p /app/.cache && chmod 777 /app/.cache
```

In Kubernetes, use an `emptyDir` volume:

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
[cache]
max_size_mb = 500
ttl = 3600  # Entries expire after 1 hour
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
[cache]
ttl = 300  # 5 minutes
```

To clear the cache programmatically:

```python
cache = self.registry.get_service("cache")
await cache.clear()
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

**Solution:** Create a mock registry fixture and assign it to the component:

```python
import pytest
from unittest.mock import MagicMock, AsyncMock


@pytest.fixture
def mock_registry():
    registry = MagicMock()
    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value=None)
    mock_cache.set = AsyncMock()
    registry.get_service = MagicMock(side_effect=lambda name: {
        "cache": mock_cache,
    }.get(name))
    return registry


@pytest.fixture
def my_service(mock_registry):
    from src.services.my_service import MyService
    svc = MyService()
    svc.registry = mock_registry
    return svc
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
