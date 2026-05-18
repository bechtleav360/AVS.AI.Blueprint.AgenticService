# Health Check System

Comprehensive health check framework for monitoring application components and dependencies.

## Overview

The health check system provides a unified interface for monitoring the status of various application components (Dapr, AI providers, custom services, etc.). It supports:

- **Extensible architecture**: Easy to add custom health checkers
- **Async operations**: Non-blocking health checks
- **Caching**: Periodic background updates to reduce resource consumption
- **Registry pattern**: Dynamic registration and management of health checkers
- **Type safety**: Full type hints and Protocol/ABC support

## Architecture

### Core Components

```
HealthCheckerBase (Abstract Base Class)
    ├── DaprPubSubHealthChecker
    ├── VLLMProviderHealthChecker
    └── CustomHealthChecker (user-defined)

HealthCheckerRegistry
    └── Manages all registered health checkers

HealthCheckCache
    └── Caches health check results with periodic updates

ActuatorApi
    └── Exposes health check endpoints (/health/live, /health/ready)
```

## Classes

### 1. HealthCheckerBase

**Location**: `base.py`

Abstract base class that all health checkers must inherit from.

```python
from blueprint.agents.services.health import HealthCheckerBase
from blueprint.agents.models.api import ComponentHealth

class CustomHealthChecker(HealthCheckerBase):
    async def health_check(self) -> ComponentHealth:
        """Perform health check logic."""
        try:
            # Check component status
            is_healthy = await check_service()
            return ComponentHealth(
                status="UP" if is_healthy else "DOWN",
                message="Service is operational" if is_healthy else "Service unavailable"
            )
        except Exception as e:
            return ComponentHealth(status="DOWN", message=str(e))
```

**Key Method**:
- `async def health_check(self) -> ComponentHealth`: Perform health check and return status

**Returns**: `ComponentHealth` object with:
- `status`: "UP" or "DOWN"
- `message`: Human-readable status message

### 2. DaprPubSubHealthChecker

**Location**: `dapr_pubsub.py`

Monitors Dapr sidecar availability and pub/sub connectivity.

```python
from blueprint.agents.services.health import DaprPubSubHealthChecker
from blueprint.agents.config import Config

config = Config(...)
checker = DaprPubSubHealthChecker(config)
status = await checker.health_check()
```

**Configuration**:
- `health_check_dapr`: Enable/disable Dapr checks (default: True)
- `dapr_http_port`: Dapr HTTP port (default: 3500)

**Checks**:
- Dapr sidecar reachability via `/v1.0/healthz` endpoint

### 3. VLLMProviderHealthChecker

**Location**: `vllm_provider.py`

Monitors AI model provider health (vLLM, OpenAI).

```python
from blueprint.agents.services.health import VLLMProviderHealthChecker
from blueprint.agents.config import Config

config = Config(...)
checker = VLLMProviderHealthChecker(config, runtime_names=["default", "custom"])
status = await checker.health_check()
```

**Configuration**:
- `health_check_ai_provider`: Enable/disable AI provider checks (default: True)
- Runtime-specific AI config (base_url, api_key, model_name)

**Checks**:
- vLLM: Reachability via `/health` endpoint
- OpenAI: Configured but not actively checked (API-based)

### 4. HealthCheckerRegistry

**Location**: `registry.py`

Manages registration and retrieval of health checkers.

```python
from blueprint.agents.services.health import HealthCheckerRegistry, HealthCheckerBase

registry = HealthCheckerRegistry()

# Register a checker
registry.register("database", DatabaseHealthChecker())

# Register or replace
registry.register_or_replace("cache", CacheHealthChecker())

# Retrieve
checker = registry.get("database")

# Check existence
if registry.has("database"):
    print("Database checker registered")

# List all
all_checkers = registry.get_all()  # Returns dict[str, HealthCheckerBase]

# Get names
names = registry.list_names()  # Returns list[str]

# Clear all
registry.clear()
```

**Methods**:
- `register(name, checker)`: Register a new checker (raises ValueError if exists)
- `register_or_replace(name, checker)`: Register or replace existing
- `get(name) -> HealthCheckerBase | None`: Get checker by name
- `get_all() -> dict[str, HealthCheckerBase]`: Get all checkers
- `has(name) -> bool`: Check if registered
- `list_names() -> list[str]`: List all checker names
- `clear()`: Remove all checkers

### 5. HealthCheckCache

**Location**: `cache.py`

Caches health check results and performs periodic background updates.

```python
from blueprint.agents.services.health.cache import HealthCheckCache

cache = HealthCheckCache(check_interval_seconds=30)

# Set health check providers
providers = {
    "dapr": DaprPubSubHealthChecker(config),
    "ai_provider": VLLMProviderHealthChecker(config)
}
cache.set_health_check_provider(providers)

# Start background scheduler
await cache.start()

# Get cached results
results = await cache.get_health_checks()

# Stop scheduler
await cache.stop()
```

## Usage Patterns

### Pattern 1: Using AppBuilder

```python
from blueprint.agents import AppBuilder, Config
from blueprint.agents.services.health import HealthCheckerBase
from blueprint.agents.models.api import ComponentHealth

class DatabaseHealthChecker(HealthCheckerBase):
    async def health_check(self) -> ComponentHealth:
        # Check database connection
        return ComponentHealth(status="UP", message="DB OK")

config = Config(...)
builder = AppBuilder(config)

# Register custom health checker
builder.with_health_checker("database", DatabaseHealthChecker())
builder.with_health_checker("cache", CacheHealthChecker())

app = builder.build()
```

### Pattern 2: Direct Registry Usage

```python
from blueprint.agents.services.health import HealthCheckerRegistry, HealthCheckerBase

registry = HealthCheckerRegistry()

# Register multiple checkers
registry.register("service1", Service1HealthChecker())
registry.register("service2", Service2HealthChecker())

# Get all for ActuatorApi
all_checkers = registry.get_all()
```

### Pattern 3: Custom Health Checker

```python
from blueprint.agents.services.health import HealthCheckerBase
from blueprint.agents.models.api import ComponentHealth
import httpx

class ExternalAPIHealthChecker(HealthCheckerBase):
    def __init__(self, api_url: str):
        self.api_url = api_url

    async def health_check(self) -> ComponentHealth:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.api_url}/health")
                response.raise_for_status()
                return ComponentHealth(
                    status="UP",
                    message=f"API reachable at {self.api_url}"
                )
        except Exception as e:
            return ComponentHealth(
                status="DOWN",
                message=f"API unreachable: {e}"
            )
```

## Integration with AppBuilder

The health check system is fully integrated into `AppBuilder`:

```python
builder = AppBuilder(config)

# Default health checkers are automatically registered:
# - DaprPubSubHealthChecker (if Dapr enabled)
# - VLLMProviderHealthChecker (if agents registered)

# Add custom health checkers
builder.with_health_checker("custom", CustomHealthChecker())

# Build app with all health checks
app = builder.build()
```

**Endpoints**:
- `GET /health/live`: Liveness probe (always returns 200 if app is running)
- `GET /health/ready`: Readiness probe (returns 200 only if all health checks pass)
- `GET /info`: Service information and dependency status

## Health Check Results

Health checks return `ComponentHealth` objects:

```python
from blueprint.agents.models.api import ComponentHealth

health = ComponentHealth(
    status="UP",  # or "DOWN"
    message="Service is operational"
)

# Response format
{
    "status": "UP",
    "message": "Service is operational"
}
```

## Configuration

Health checks are configured via `Config`:

```python
# settings.toml
[health_check]
health_check_dapr = true
health_check_ai_provider = true
health_check_interval_seconds = 30
dapr_http_port = 3500
```

## Best Practices

1. **Inherit from HealthCheckerBase**: All custom health checkers must inherit from the abstract base class
2. **Handle Exceptions**: Always catch exceptions and return appropriate `ComponentHealth` status
3. **Use Timeouts**: Set reasonable timeouts for external service checks
4. **Log Appropriately**: Use DEBUG for successful checks, WARNING for failures
5. **Keep Checks Fast**: Health checks should complete within seconds
6. **Register Early**: Register health checkers before building the app

## Example: Complete Setup

```python
from blueprint.agents import AppBuilder, Config
from blueprint.agents.services.health import HealthCheckerBase
from blueprint.agents.models.api import ComponentHealth
from pathlib import Path

# Define custom health checker
class RedisHealthChecker(HealthCheckerBase):
    def __init__(self, redis_url: str):
        self.redis_url = redis_url

    async def health_check(self) -> ComponentHealth:
        try:
            import redis.asyncio as redis
            r = await redis.from_url(self.redis_url, socket_connect_timeout=2)
            await r.ping()
            await r.close()
            return ComponentHealth(status="UP", message="Redis OK")
        except Exception as e:
            return ComponentHealth(status="DOWN", message=f"Redis error: {e}")

# Setup
config = Config(
    settings_files=["settings.toml"],
    root_path=Path(__file__).parent
)

builder = AppBuilder(config)

# Register custom health checkers
builder.with_health_checker("redis", RedisHealthChecker("redis://localhost:6379"))
builder.with_health_checker("database", DatabaseHealthChecker())

# Build app
app = builder.build()

# Health endpoints are now available:
# GET /health/live -> Liveness probe
# GET /health/ready -> Readiness probe with all checks
# GET /info -> Service info
```

## Testing

```python
import pytest
from blueprint.agents.services.health import HealthCheckerBase
from blueprint.agents.models.api import ComponentHealth

class TestHealthChecker(HealthCheckerBase):
    async def health_check(self) -> ComponentHealth:
        return ComponentHealth(status="UP", message="Test OK")

@pytest.mark.asyncio
async def test_health_checker():
    checker = TestHealthChecker()
    result = await checker.health_check()
    assert result.status == "UP"
    assert "Test OK" in result.message
```

## Files

- `base.py`: Abstract base class `HealthCheckerBase`
- `dapr_pubsub.py`: Dapr health checker implementation
- `vllm_provider.py`: AI provider health checker implementation
- `registry.py`: Health checker registry
- `cache.py`: Health check result caching with background updates
- `__init__.py`: Module exports

## See Also

- `ActuatorApi`: Exposes health check endpoints
- `HealthCheckCache`: Caches health check results
- `AppBuilder.with_health_checker()`: Register custom health checkers
