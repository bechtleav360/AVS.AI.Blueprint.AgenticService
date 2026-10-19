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

Event handlers form an ordered chain. When an event arrives, the framework asks the handlers in
priority order whether they are responsible for it (`can_handle_event`); the first one that is runs
`handle_event`, and **the first result that is not `None` ends the chain**.

### Handler Priority

Handlers are sorted by their `priority` (lower values are asked earlier), set through the base
class constructor:

```python
from typing import Any

from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent, HandlerResult


class DocumentHandler(EventHandlerBase):
    def __init__(self) -> None:
        super().__init__(priority=10)

    async def on_startup(self) -> None:
        self._service = self.registry.get_service(DocumentService)

    async def on_shutdown(self) -> None:
        pass

    async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
        return event.type == "document.received"

    async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> HandlerResult:
        payload = self.extract_payload(event, DocumentReceived)
        enriched = await self._service.enrich(payload.document_id)
        if enriched is None:
            return HandlerResult.skipped("document already enriched")
        return HandlerResult(event_type="document.enriched", data=enriched.model_dump())
```

### Handler Methods

Every handler implements two methods, both `async` and both given the event and the processing
`context`:

- **`can_handle_event(event, context)`** -- routing: return `True` if this handler is responsible for
  this kind of event. Decide on the envelope only (`type`, `source`, `subject`, context keys) --
  no I/O, no service call. Called for every incoming event until one handler says yes.
- **`handle_event(event, context)`** -- translation: extract the payload, make **one** service call,
  and return the answer as a result. Whether this particular event needs work is the service's
  decision.

## Return Values from handle_event

The return value of `handle_event()` determines what happens next:

| Return value | Chain | Published | Delivery |
|---|---|---|---|
| `None` | continues with the next handler | nothing | acked when the chain ends; if no handler returned anything, "No handler processed event" is logged |
| `HandlerResult(event_type=...)` | stops | the event, if `event_type` is in `topic_mapping` | acked after publishing |
| `list[HandlerResult]` | stops | each result | acked after publishing |
| `HandlerResult.skipped(reason)` | stops | nothing | acked; reason logged at INFO; counted as `blueprint.events.skipped` |
| a `dict` | stops | nothing, unless it carries an `event_type` key | acked; the dict is the run's result (e.g. for a REST caller) |
| an exception | stops | nothing | not acked -- redelivered (see the transport sections) |

### Return None -- Offer the Event to the Next Handler

`None` means "not mine after all": the event goes on to the next handler. Use it only when another
handler should get the event.

### Return HandlerResult -- Publish a Downstream Event

Returning a `HandlerResult` causes the framework to publish a new event to the configured event bus.

```python
return HandlerResult(event_type="document.summarized", data={"summary": summary, "original_id": event.id})
```

### Return a List of HandlerResult -- Publish Multiple Events

Returning a list publishes multiple downstream events, useful for fan-out patterns.

```python
return [HandlerResult(event_type="chunk.created", data={"chunk": chunk, "index": i}) for i, chunk in enumerate(chunks)]
```

### Return HandlerResult.skipped -- Responsible, Nothing to Do

The handler owns the event, and its service decided that this particular event needs nothing (the
status did not change, the document is already processed). The chain stops, nothing is published,
the delivery is acknowledged, and the reason is logged at INFO and counted as
`blueprint.events.skipped` -- apart from unhandled events, which say something about the
subscription rather than about the agent's rules. The run's status is `ProcessingStatus.SKIPPED`.

```python
outcome = await self._service.on_project_updated(payload.project_id, event_id=event.id)
if outcome is None:
    return HandlerResult.skipped("project not relevant for this agent")
```

### When publishing a result fails

**A result that cannot be published fails the delivery.** The inbound event is not acknowledged: it
is redelivered, and the handler runs again -- including any LLM call it makes. This is the same
at-least-once contract as a handler that raises; the alternative is an event marked processed
whose output was never sent. If deduplication is enabled, the marker for the inbound event is
released, so the redelivery is not skipped as a duplicate.

That holds for every delivery that is not acknowledged, not only for a failed publish: **with
deduplication on, a delivery keeps its marker only when it ends in an `ack`.** A handler that
raises, a run cut off by `nats_handler_timeout` or by a shutdown -- including a handler that
catches the cancellation and returns anyway -- and a return value that cannot be turned into
results all release the marker before the delivery is nak'd. A duplicate never releases the marker
it ran into: that marker belongs to the first delivery.

**A result's event id is derived, not random:** a UUIDv5 over the agent, the inbound event's
`source` and `id`, the result's `event_type` and its position in the list. A redelivery therefore
republishes each result under the same id -- including results an earlier attempt had already sent
before a later one failed -- and a consumer that deduplicates on `source` + `id` sees each result
once. Keep the order of a returned list stable for the same input.

Two cases are skipped with a WARNING rather than failed, because they are configuration rather than
a failure: an `event_type` with no entry in `topic_mapping`, and a result that would be published
to the topic its inbound event came from.

### Return a dict

A `dict` ends the chain like a result: with an `event_type` key it is published like a `HandlerResult`, otherwise it is the run's result (a REST
caller receives it as `data`). It is not handed to another handler.

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

### JetStream delivery

With `nats_use_jetstream = true` the framework creates one **durable consumer per topic** on the
configured stream and binds every replica to it through the agent's queue group, so exactly one
replica handles each message. What happens to a delivery is decided at the transport edge:

**`nats_use_jetstream` is checked against the server.** On connecting, the framework asks the
server for the account's JetStream information. If JetStream is not there -- not enabled on the
server, or not for this account -- the agent fails, and there is no fallback to Core NATS: that
would silently drop durable consumers and acknowledgements. At startup the startup failure policy
applies. If the broker was unreachable at startup and the mismatch shows up later, the root or a
critical agent shuts the process down (SIGTERM to itself, so the other agents still drain), and a
non-critical agent is marked down until the pod restarts. A timeout on that request is not treated
as an answer; it is retried like any other connection failure.

**A delivery is acknowledged only when its work is complete.** Complete means the handler chain
returned *and* every result it returned was published. Anything short of that is never an `ack`:
it is a `nak`, so the event is delivered again, or a dead letter when retrying cannot help. An
`ack` for work that did not finish would tell the broker the event is done while its outcome is
lost -- nothing redelivers it and nothing records it.

| Outcome | Disposition |
|---------|-------------|
| The handler chain returned and every result was published, including "no handler matched" | `ack` |
| A result could not be published | `nak` -- the handler runs again on redelivery; with deduplication on, its marker is released first |
| `RetryableHandlerError`, or any unexpected exception | `nak` -- redelivered after `nats_ack_wait` |
| `InvalidEventError` or `CriticalHandlerError` | dead-lettered, then `term` |
| The payload is not a parseable CloudEvent | dead-lettered, then `term` |
| The last delivery `nats_max_deliver` allows failed again (only when `nats_max_deliver` is set) | dead-lettered, then `term` |

Dead-lettering republishes the **original bytes**, unchanged, to `nats_dead_letter_subject`, with
the reason, the original subject, the delivery count and the event id in headers. The subject is
added to the stream when the framework provisions it, so dead letters are persisted rather than
dropped on the floor, and consuming them is an ordinary subscription.

Two settings interact and are worth choosing together. The framework sets neither on its own --
unset, each is the server's default:

- **`nats_ack_wait` must exceed your slowest handler.** It is the broker's patience, not the
  client's: when it expires the message is redelivered to another replica while the first one is
  still working, so a model call that occasionally takes four minutes needs an `ack_wait` above
  four minutes, not the NATS default of thirty seconds.
- **`nats_max_ack_pending` should stay close to replicas x `nats_max_concurrent_runs`.** A pod
  starts at most `nats_max_concurrent_runs` runs; anything the broker pushes beyond that waits in
  the client's queue -- where its `ack_wait` is already counting down, unhandled and without a
  heartbeat.

**How many deliveries run at once.** Each delivery runs as its own task, up to
`nats_max_concurrent_runs` per agent and process, shared by its subscriptions (unset: one at a time
per subscription, as before the key existed). The subscription
waits for a free slot before it takes the next message, so a full agent stops taking work rather
than starting more. Order within a subject is not kept beyond one run at a time.

**Long runs are kept alive.** While a JetStream run is in progress, its delivery is reported
`in_progress` every third of the consumer's `ack_wait` -- the value the broker has, not
`nats_ack_wait`, since an existing consumer keeps its own. A run longer than `ack_wait` is
therefore not redelivered while it still runs. A message still waiting for a slot gets no
heartbeat. `nats_heartbeat_enabled = false` switches the heartbeat off for an agent.

**A run can be bounded.** The heartbeat proves the process is alive, not that the run makes progress:
a hung model request would hold its slot -- and, with one run per subscription, every later event of
that subscription -- forever. `nats_handler_timeout` cancels a run at the limit and naks its delivery
for immediate redelivery, up to `nats_max_deliver` attempts. Whether the limit was hit is read from
the run's own timer: a `TimeoutError` raised by the handler is an ordinary failure.

An existing consumer is never rewritten. Its filter subject and deliver group are broker-side
state that the stream's redelivery bookkeeping hangs off, so changing them is a migration: the
client logs which settings differ and keeps consuming with the ones the broker already has. Apply
new values by deleting the consumer during a maintenance window.

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

> **Agent registration (sessions v0.4.0+):** Before opening the SSE job stream, `SessionsBus` calls
> `POST /agents/register` to declare its `agent_id`, `agent_type`, and `capabilities` — the dispatch
> source of truth. It re-registers before every reconnect attempt (idempotent), and on graceful
> shutdown it drains in-flight jobs and unregisters (`DELETE /agents/{agent_id}`). Against a pre-v0.4.0
> server the register call returns 404 and is skipped ("legacy, proceed without registration").

> **Reconnect catch-up:** SSE only pushes jobs created *while connected*, so jobs created during a
> restart, redeploy, or stream gap would otherwise be missed. On every (re)connect `SessionsBus`
> reconciles in two ways: it resumes the stream with `Last-Event-ID` (the server replays missed
> frames from its ring buffer on a same-process reconnect), and it runs a REST **catch-up** —
> `GET /jobs?status=pending` for its capabilities — dispatching any pending jobs through the normal
> handler path. Both feed the same idempotent handler, so a job that arrives via more than one route
> is processed once. Catch-up is best-effort: a listing failure is logged and never disturbs the live
> stream. A job stranded in `running` because its previous owner crashed is recovered server-side
> (the sessions reaper re-pends it) and then redelivered by this catch-up.

```toml
[default]
event_bus = "sessions"

[default.sessions_service]
base_url = "http://sessions:8000"
agent_id = "my-agent"
agent_type = "analyser"
capabilities = ["analyse_documents"]
api_key = "@format {env[SESSIONS_API_KEY]}"
# Optional per-agent HS256 bearer. Sent as `Authorization: Bearer <token>` alongside
# `X-Api-Key` on the gated routes only when set. See service-sessions#198/#326. Inject via
# SESSIONS_AGENT_TOKEN, never commit it. To opt out, OMIT this line (or export an empty
# SESSIONS_AGENT_TOKEN=) — keeping it with the env var undefined fails Dynaconf config load.
agent_token = "@format {env[SESSIONS_AGENT_TOKEN]}"
max_concurrent_jobs = 5
job_timeout_seconds = 300
```

## Complete Handler Example

```python
from typing import Any

from pydantic import BaseModel

from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent, HandlerResult


class DocumentChanged(BaseModel):
    """DTO: the payload of document.received / document.updated."""

    document_id: str


class IngestionHandler(EventHandlerBase):
    def __init__(self) -> None:
        super().__init__(priority=5)

    async def on_startup(self) -> None:
        self._ingestion = self.registry.get_service(IngestionService)

    async def on_shutdown(self) -> None:
        pass

    async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
        return event.type in ("document.received", "document.updated")

    async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> HandlerResult:
        payload = self.extract_payload(event, DocumentChanged)
        stored = await self._ingestion.ingest(payload.document_id, event_id=event.id)
        if stored is None:
            return HandlerResult.skipped("document already ingested")
        return HandlerResult(event_type="document.stored", data={"doc_id": stored.document_id})

    def get_published_event_types(self) -> tuple[str, str] | None:
        return ("document.stored", "document.ingestion_error")
```

The deduplication ("already ingested"), the storage and the cache all live in `IngestionService`;
the handler only translates.
