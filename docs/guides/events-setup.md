# Event-Driven Processing with Dapr

**Time to complete:** 10 minutes
**Difficulty:** Intermediate

This guide shows how to implement event-driven workflows for the Agents Blueprint on Kubernetes. For Dapr fundamentals and architecture, see [Dapr Fundamentals](../concepts/dapr-fundamentals.md).

## Overview

The platform provides RabbitMQ and auto-injects Dapr sidecars. Your agent only needs to:
1. Implement REST endpoints for event processing
2. Configure subscriptions
3. Publish events via the Dapr sidecar API

## REST Endpoints

### Event Processing
```python
@app.post("/events/process")
async def process_event(event: CloudEvent) -> dict:
    """Receive events from Dapr sidecar"""
    return {"status": "processed"}
```

### Health Check (Optional)
```python
@app.get("/health/live")
async def health_check() -> dict:
    return {"status": "healthy"}
```

## Subscriptions

Create subscription files:

```yaml
# custom/dapr/subscriptions/invoice-events.yaml
apiVersion: dapr.io/v2alpha1
kind: Subscription
metadata:
  name: invoice-events
spec:
  pubsubname: pubsub
  topic: invoice.created
  route: /events/process
  deadLetterTopic: invoice.dlq
```

## Publication Topic Configuration

Configure topics in `settings.toml`:

```toml
[event_publishing]
enabled = true

[event_publishing.topic_mapping]
"invoice.created" = { topic = "invoice.created", pubsub = "pubsub" }
"invoice.processed" = { topic = "invoice.processed", pubsub = "pubsub" }
"asset.verified" = { topic = "asset.verified", pubsub = "pubsub" }
```

The topic mapping defines:
- **Event type** (key) - The logical event name in your code
- **Topic** - The actual RabbitMQ topic name
- **Pubsub** - The Dapr component name (usually "pubsub")

## Publishing Events

### How Events Are Published

Events flow through this architecture:

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Agent     │───►│ Dapr Sidecar│───►│ RabbitMQ    │───►│ Subscribers │
│ Publisher   │    │ (localhost) │    │ Broker      │    │ (Agents)    │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

1. **Agent creates event** - Your code generates an event with data
2. **Dapr sidecar receives** - Event sent to `localhost:3500/v1.0/publish/{pubsub}/{topic}`
3. **RabbitMQ distributes** - Sidecar forwards to managed RabbitMQ broker
4. **Subscribers receive** - Dapr routes events to subscribed agents

### From Agent (Using Config)
```python
from blueprint.services.processing import EventPublisher

# EventPublisher uses topic mapping from settings.toml
publisher = EventPublisher()
await publisher.publish("invoice.processed", {
    "invoice_id": "inv-123",
    "status": "completed"
})
```

### From Agent (Direct API)
```python
import httpx

async def publish_result(event_data: dict):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:3500/v1.0/publish/pubsub/results",
            json=event_data
        )
        return response.json()
```

### From External Service
```bash
curl -X POST http://<agent-service>:3500/v1.0/publish/pubsub/results \
  -H "Content-Type: application/json" \
  -d '{"key": "value"}'
```

## Deployment

Add Dapr annotations to your Deployment:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agent-blueprint
spec:
  template:
    metadata:
      annotations:
        dapr.io/enabled: "true"
        dapr.io/app-id: agent-blueprint
        dapr.io/app-port: "8001"
        dapr.io/enable-api-logging: "true"
```

## Testing

1. Port-forward: `kubectl port-forward svc/agent-blueprint 8001:8001`
2. Open Swagger UI: `http://localhost:8001/docs`
3. Test `/events/process` endpoint
4. Check logs: `kubectl logs -f deployment/agent-blueprint -c agent`

## Quick Reference

| Component | Endpoint/Location |
|-----------|-------------------|
| Dapr sidecar | `http://localhost:3500` |
| Event endpoint | `/events/process` |
| Health endpoint | `/health/live` |
| Subscriptions | `custom/dapr/subscriptions/` |
| Publish API | `POST /v1.0/publish/{pubsub}/{topic}` |
