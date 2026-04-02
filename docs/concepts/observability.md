# Observability

Blueprint Agents provides built-in observability through OpenTelemetry tracing, structured logging, metrics collection, and health check endpoints. These capabilities are designed to work out of the box with minimal configuration while remaining extensible for advanced use cases.

## OpenTelemetry Tracing

The framework integrates with OpenTelemetry to produce distributed traces exported via the OTLP protocol. When enabled, traces capture the full request lifecycle including HTTP handling, event processing, and AI model invocations.

### Configuration

Enable tracing in `settings.toml`:

```toml
[default]
otel_enabled = true
otel_endpoint = "http://localhost:4317"
otel_service_name = "document-processor"
```

| Field | Type | Description |
|---|---|---|
| `otel_enabled` | `bool` | Enable or disable OpenTelemetry tracing |
| `otel_endpoint` | `str` | OTLP collector endpoint (gRPC) |
| `otel_service_name` | `str` | Service name attached to all spans and metrics |

### Automatic FastAPI Instrumentation

When tracing is enabled, the framework automatically instruments the FastAPI application. Every incoming HTTP request generates a span with method, path, status code, and duration attributes. No additional code is required.

### Automatic CloudEvent Attribute Extraction

When an event handler processes a CloudEvent, the framework automatically extracts event metadata and attaches it to the active span:

- `cloudevent.id` -- The unique event identifier
- `cloudevent.type` -- The event type string
- `cloudevent.source` -- The event source URI
- `cloudevent.subject` -- The event subject

This makes it straightforward to correlate traces with specific events in your observability backend.

## The @traced() Decorator

For custom spans on application-specific logic, use the `@traced()` decorator on any async method:

```python
from blueprint.agents.services.service_base import ServiceBase
from blueprint.agents.observability import traced


class EmbeddingService(ServiceBase):
    async def on_startup(self) -> None:
        self.model = self.registry.get_agent("embedder")

    @traced()
    async def compute_embedding(self, text: str) -> list[float]:
        # This method is wrapped in a span named "EmbeddingService.compute_embedding"
        return await self.model.run(text)

    @traced()
    async def batch_embed(self, texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            embedding = await self.compute_embedding(text)
            results.append(embedding)
        return results
```

The decorator creates a span named `{ClassName}.{method_name}` by default. Nested `@traced()` calls produce parent-child span relationships, giving full visibility into call hierarchies.

### Custom Span Names

Pass a name argument to override the default span name:

```python
@traced("embedding.compute")
async def compute_embedding(self, text: str) -> list[float]:
    return await self.model.run(text)
```

## Metrics

The framework automatically collects and exports metrics related to AI model usage and request processing.

### Token Usage Metrics

For every AI agent invocation, the following metrics are recorded:

| Metric | Description |
|---|---|
| `ai.tokens.prompt` | Number of tokens in the prompt |
| `ai.tokens.completion` | Number of tokens in the model response |
| `ai.tokens.total` | Total tokens consumed (prompt + completion) |

### Request Metrics

| Metric | Description |
|---|---|
| `ai.request.latency` | Duration of the model request in milliseconds |
| `ai.request.model_provider` | The provider used (e.g., "openai", "anthropic") |
| `ai.request.model_name` | The specific model invoked (e.g., "gpt-4o") |

These metrics are exported alongside traces through the configured OTLP endpoint and can be visualized in Grafana, Datadog, or any OpenTelemetry-compatible backend.

## Structured Logging

Blueprint Agents uses structured logging with correlation context. Log messages are formatted with key-value pairs that are queryable in log aggregation systems.

### Formatting Convention

Use `%s`-style string formatting in log statements, not f-strings. This allows log aggregators to group identical log patterns and enables lazy evaluation (the string is only formatted if the log level is active).

```python
import logging

logger = logging.getLogger(__name__)


class DocumentHandler(EventHandlerBase):
    async def handle_event(self, event: CloudEvent) -> HandlerResult:
        # Correct: %s-style formatting
        logger.info("Processing document %s from source %s", event.subject, event.source)

        # Incorrect: f-string formatting (defeats structured logging)
        # logger.info(f"Processing document {event.subject} from source {event.source}")

        result = await self.process(event)
        logger.debug("Processing complete for %s, result size: %d", event.subject, len(result))

        return HandlerResult(event_type="document.processed", data=result)
```

### Log Level Configuration

Set the log level in `settings.toml`:

```toml
[default]
log_level = "INFO"   # DEBUG, INFO, WARNING, ERROR, CRITICAL
```

### Correlation Context

When tracing is enabled, the active trace ID and span ID are automatically injected into log records. This allows you to correlate log entries with specific traces in your observability stack.

## Health Checks

The framework automatically registers health check endpoints on the FastAPI application. These endpoints follow standard conventions for container orchestration platforms such as Kubernetes.

### Built-in Endpoints

| Endpoint | Purpose | Description |
|---|---|---|
| `/health/live` | Liveness probe | Returns 200 if the process is running. Used by orchestrators to detect crashed processes. |
| `/health/ready` | Readiness probe | Returns 200 if the application is ready to accept traffic. Checks that all components have completed startup. |
| `/health/detailed` | Detailed status | Returns a JSON breakdown of each component's health status. Useful for debugging. |

### Response Format

The `/health/detailed` endpoint returns structured information about each component:

```json
{
  "status": "healthy",
  "components": {
    "EmbeddingService": {"status": "healthy"},
    "DocumentHandler": {"status": "healthy"},
    "summarizer": {"status": "healthy", "type": "agent"},
    "cache": {"status": "healthy", "entries": 1523}
  },
  "uptime_seconds": 3847
}
```

### Custom Health Checkers

Register custom health check logic using `.with_health_checker()` on the `AppBuilder`. This is useful for verifying connectivity to external dependencies.

```python
from blueprint.agents import AppBuilder, Config


async def check_database(registry) -> dict:
    """Custom health check for database connectivity."""
    try:
        db = registry.get_service(DatabaseService)
        await db.ping()
        return {"status": "healthy", "latency_ms": 12}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


async def check_external_api(registry) -> dict:
    """Custom health check for an external API."""
    try:
        client = registry.get_service(ExternalApiClient)
        await client.health_check()
        return {"status": "healthy"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


config = Config(settings_files=["settings.toml"])

app = (
    AppBuilder(config)
    .with_service(DatabaseService)
    .with_service(ExternalApiClient)
    .with_handler(MyHandler)
    .with_health_checker("database", check_database)
    .with_health_checker("external_api", check_external_api)
    .build()
)
```

Custom health checkers appear in the `/health/detailed` response and influence the `/health/ready` status. If any checker returns `"unhealthy"`, the readiness endpoint returns a 503 status code.

## Complete Configuration Example

```toml
[default]
app_name = "document-processor"
log_level = "INFO"

# OpenTelemetry
otel_enabled = true
otel_endpoint = "http://otel-collector:4317"
otel_service_name = "document-processor"
```

## Complete Code Example

```python
import logging

from blueprint.agents import AppBuilder, Config
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.services.service_base import ServiceBase
from blueprint.agents.models.events import CloudEvent, HandlerResult
from blueprint.agents.observability import traced

logger = logging.getLogger(__name__)


class AnalyticsService(ServiceBase):
    async def on_startup(self) -> None:
        self.agent = self.registry.get_agent("analyzer")

    @traced()
    async def analyze(self, content: str) -> dict:
        logger.info("Starting analysis, content length: %d", len(content))
        result = await self.agent.run(content)
        logger.info("Analysis complete, categories found: %d", len(result.get("categories", [])))
        return result


class AnalyticsHandler(EventHandlerBase):
    priority = 10

    async def on_startup(self) -> None:
        self.analytics = self.registry.get_service(AnalyticsService)

    def can_handle_event(self, event: CloudEvent) -> bool:
        return event.type == "document.received"

    @traced()
    async def handle_event(self, event: CloudEvent) -> HandlerResult:
        logger.info("Handling event %s for subject %s", event.type, event.subject)
        result = await self.analytics.analyze(event.data["content"])
        return HandlerResult(
            event_type="document.analyzed",
            data={"doc_id": event.subject, "analysis": result},
        )

    def get_published_event_types(self) -> list[str]:
        return ["document.analyzed", "document.analysis_error"]


async def check_model_health(registry) -> dict:
    try:
        agent = registry.get_agent("analyzer")
        await agent.health_check()
        return {"status": "healthy"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


config = Config(settings_files=["settings.toml", "secrets.toml"])

app = (
    AppBuilder(config)
    .with_service(AnalyticsService)
    .with_handler(AnalyticsHandler)
    .with_agent("analyzer", AnalyzerAgent)
    .with_health_checker("analyzer_model", check_model_health)
    .with_cache()
    .build()
)
```
