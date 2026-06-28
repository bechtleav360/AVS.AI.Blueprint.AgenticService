# Event Processing

Blueprint Agents uses the CloudEvents v1.0 specification as its universal message format. Events flow through a handler chain where each handler can inspect, process, transform, or forward events to downstream consumers.

## CloudEvent Model

The framework provides a generic `CloudEvent[T]` model that wraps the standard CloudEvents attributes with a typed data payload.

```python
from blueprint.agents.models.events import CloudEvent, GenericCloudEvent
```

### Core Fields

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Unique event identifier (UUID by default) |
| `type` | `str` | Event type identifier, e.g. `"document.received"` |
| `source` | `str` | URI identifying the event producer |
| `subject` | `str` | Subject of the event in context of the source |
| `time` | `datetime` | Timestamp when the event was created |
| `data` | `T` | The event payload, typed by the generic parameter |

### GenericCloudEvent

For cases where the data payload does not require a specific schema, use the pre-defined alias:

```python
# GenericCloudEvent is equivalent to CloudEvent[dict[str, Any]]
event = GenericCloudEvent(
    type="document.received",
    source="/ingest/api",
    subject="doc-12345",
    data={"content": "The full document text...", "format": "plaintext"},
)
```

### Typed Events

For structured payloads, parameterize `CloudEvent` with a Pydantic model or dataclass:

```python
from pydantic import BaseModel
from blueprint.agents.models.events import CloudEvent


class DocumentPayload(BaseModel):
    content: str
    format: str
    word_count: int


event: CloudEvent[DocumentPayload] = CloudEvent(
    type="document.received",
    source="/ingest/api",
    subject="doc-12345",
    data=DocumentPayload(content="...", format="plaintext", word_count=1500),
)
```

## Handler Chain-of-Responsibility

Event handlers form an ordered processing chain. When an event arrives, the framework iterates through registered handlers, asks each whether it can handle the event, and delegates processing to those that accept it.

### Handler Priority

Handlers are sorted by their `priority` attribute (lower values execute earlier). This determines the order in which handlers are consulted for each incoming event.

```python
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import CloudEvent


class ValidationHandler(EventHandlerBase):
    priority = 1  # Runs first

    def can_handle_event(self, event: CloudEvent) -> bool:
        return event.type == "document.received"

    async def handle_event(self, event: CloudEvent) -> None:
        if not event.data.get("content"):
            raise ValueError("Empty document content")
        # Return None to pass the event to the next handler
        return None


class EnrichmentHandler(EventHandlerBase):
    priority = 10  # Runs after validation

    def can_handle_event(self, event: CloudEvent) -> bool:
        return event.type == "document.received"

    async def handle_event(self, event: CloudEvent) -> HandlerResult:
        enriched = await self.enrich(event.data)
        return HandlerResult(event_type="document.enriched", data=enriched)
```

### Handler Methods

Every handler must implement two methods:

- **`can_handle_event(event)`** -- Return `True` if this handler should process the given event. Called for every incoming event.
- **`handle_event(event)`** -- Process the event and return a result that controls downstream behavior.

## Return Values from handle_event

The return value of `handle_event()` determines what happens after processing:

### Return None -- Pass to Next Handler

Returning `None` or not returning signals that the handler has finished its work (or declined to act) and the event should continue to the next handler in the chain.

```python
async def handle_event(self, event: CloudEvent) -> None:
    await self.log_event(event)
    return None  # Continue chain
```

### Return HandlerResult -- Publish a Downstream Event

Returning a `HandlerResult` causes the framework to publish a new event to the configured event bus.

```python
from blueprint.agents.models.events import HandlerResult


async def handle_event(self, event: CloudEvent) -> HandlerResult:
    summary = await self.summarize(event.data["content"])
    return HandlerResult(
        event_type="document.summarized",
        data={"summary": summary, "original_id": event.id},
    )
```

### Return a List of HandlerResult -- Publish Multiple Events

Returning a list publishes multiple downstream events, useful for fan-out patterns.

```python
async def handle_event(self, event: CloudEvent) -> list[HandlerResult]:
    chunks = self.split_document(event.data["content"])
    return [
        HandlerResult(
            event_type="chunk.created",
            data={"chunk": chunk, "index": i},
        )
        for i, chunk in enumerate(chunks)
    ]
```

### Return Any Other Value -- Internal Chaining

Returning any other value passes it along internally within the handler chain without publishing to the event bus. This is useful for in-process data transformation between handlers.

```python
async def handle_event(self, event: CloudEvent) -> dict:
    # This result is available to the next handler but is not published
    return {"validated": True, "timestamp": datetime.utcnow().isoformat()}
```

## Declaring Published Event Types

Each handler should declare the event types it may produce. The framework uses this metadata for validation and documentation.

```python
class DocumentHandler(EventHandlerBase):
    def get_published_event_types(self) -> list[str]:
        return ["document.summarized", "document.error"]
```

## Event Bus Configuration

Blueprint Agents supports two event bus backends: Dapr and NATS. The choice is made in `settings.toml`.

### Selecting the Event Bus

```toml
[default]
event_bus = "dapr"   # "dapr", "nats", or "sessions"
```

### Topic Mapping

Map event types to topics so the framework knows where to publish each event:

```toml
[default.event_publishing]
default_pubsub_name = "pubsub"

[default.event_publishing.topic_mapping]
"document.received" = "documents-inbound"
"document.summarized" = "documents-processed"
"document.error" = "documents-errors"
```

## Dapr Event Bus

When `event_bus = "dapr"`, the framework integrates with the Dapr sidecar for pub/sub messaging.

- **Receiving events**: The application exposes an HTTP endpoint at `/events/{topic}`. The Dapr sidecar delivers messages by calling this endpoint.
- **Publishing events**: The framework publishes events through the Dapr sidecar HTTP API (`/v1.0/publish/{pubsub}/{topic}`).

Dapr handles message delivery guarantees, retries, and dead-letter queues through its component configuration.

```toml
[default]
event_bus = "dapr"

[default.event_publishing]
default_pubsub_name = "pubsub"

[default.event_publishing.topic_mapping]
"document.received" = "documents"
```

## NATS Event Bus

When `event_bus = "nats"`, the framework connects directly to a NATS server.

- **Receiving events**: The framework subscribes to NATS subjects mapped from topic names.
- **Publishing events**: Messages are published directly to NATS subjects.
- **JetStream**: Optional JetStream support provides persistence, replay, and at-least-once delivery guarantees.

```toml
[default]
event_bus = "nats"
nats_url = "nats://localhost:4222"

[default.event_publishing]
default_pubsub_name = "default"

[default.event_publishing.topic_mapping]
"document.received" = "documents.inbound"
"document.summarized" = "documents.processed"
```

## Broker Startup Resilience

By default the framework does not require the broker to be reachable when the service starts. The broker connection and topic subscriptions are established in a background task so the application enters a live state immediately, even if the NATS server or Dapr sidecar is temporarily unavailable.

### Startup sequence

1. `AppBuilder.build()` completes and the FastAPI application starts.
2. `/health/live` returns `200` immediately — the process is alive.
3. The eventing component attempts to connect and subscribe in the background.
4. Until the connection succeeds, `/health/ready` returns `503` because the underlying client health check reports `unhealthy`.
5. Once the broker is reachable and all subscriptions are established, `/health/ready` returns `200`.

This behaviour is particularly useful in Kubernetes where Dapr sidecars or NATS may become available a few seconds after the application container starts.

### Configuration

```toml
# Retry indefinitely (default) — suitable for Kubernetes where the broker
# eventually becomes available.
event_client_max_retries = -1
event_client_retry_delay = 5.0

# Fail fast after 3 attempts — useful for local development to surface
# misconfiguration quickly.
event_client_max_retries = 3
event_client_retry_delay = 2.0
```

| Key | Default | Behaviour |
|-----|---------|-----------|
| `event_client_max_retries` | `-1` | `-1` = retry indefinitely. `0` = single attempt. `N` = N retries after the first failure. |
| `event_client_retry_delay` | `5.0` | Seconds between attempts. |

When all retries are exhausted (i.e. `event_client_max_retries >= 0` and the limit is reached), the error is logged at `ERROR` level with a full traceback. The application remains live but permanently not-ready.

### Kubernetes probe recommendations

Because the broker connection is asynchronous, tune the readiness probe to allow enough time for the broker to start:

```yaml
readinessProbe:
  httpGet:
    path: /health/ready
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 10
  failureThreshold: 12   # tolerate up to ~2 minutes of broker unavailability
```

---

## Sessions Transport

When `event_bus = "sessions"`, `AppBuilder.build()` wires three components automatically:

1. `SessionsApiClient` — REST client for the sessions service
2. `SessionKeyProvider` — session-key resolution with TTL cache
3. `SessionsBus` — outbound SSE consumer that converts job notifications into CloudEvents and dispatches them through the handler chain

`SessionsBus` has no inbound HTTP surface — there is no router to mount. Connection to the sessions service is established asynchronously after startup; the framework tolerates a sessions service that is unreachable at boot and retries in the background.

```toml
[default]
event_bus = "sessions"

[default.sessions_service]
base_url = "http://sessions:8000"
agent_id = "my-agent"
agent_type = "analyser"
capabilities = ["analyse_documents"]
api_key = "@format {env[SESSIONS_API_KEY]}"
max_concurrent_jobs = 5
job_timeout_seconds = 300
```

## Complete Handler Example

```python
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import CloudEvent, HandlerResult


class IngestionHandler(EventHandlerBase):
    priority = 5

    async def on_startup(self) -> None:
        self.storage = self.registry.get_service(StorageService)
        self.cache = self.registry.cache_service

    def can_handle_event(self, event: CloudEvent) -> bool:
        return event.type in ("document.received", "document.updated")

    async def handle_event(self, event: CloudEvent) -> HandlerResult | list[HandlerResult]:
        doc_id = event.subject

        # Check cache for deduplication
        cached = await self.cache.get(doc_id, namespace="ingested")
        if cached and event.type == "document.received":
            return None  # Already processed, skip

        # Store the document
        await self.storage.save(doc_id, event.data)
        await self.cache.set(doc_id, True, namespace="ingested", ttl=3600)

        # Publish downstream
        return HandlerResult(
            event_type="document.stored",
            data={"doc_id": doc_id, "source": event.source},
        )

    def get_published_event_types(self) -> list[str]:
        return ["document.stored", "document.ingestion_error"]
```
