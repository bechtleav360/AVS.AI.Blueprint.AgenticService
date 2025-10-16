# Event Routing with Routing Keys

**Time to complete:** 30 minutes  
**Difficulty:** Intermediate  
**Prerequisites:** [Setting Up Events](events-setup.md), [Creating Handlers](handlers.md)

This guide explains how to configure event routing with topics and routing keys for advanced message routing scenarios (e.g., RabbitMQ topic exchanges).

## Overview

The event publishing system supports two levels of routing configuration:

1. **Global Configuration** - Define event type to topic/routing key mappings in `values.yaml`
2. **Handler-Level Configuration** - Handlers can define their own event types and routing dynamically

## Configuration Formats

### Simple Format (Topic Only)

For basic routing without routing keys:

```yaml
eventPublishing:
  topicMapping:
    "agent.output.invoice": "invoice.events"
    "agent.status.started": "agent.status"
```

### Advanced Format (Topic + Routing Key)

For advanced routing with RabbitMQ topic exchanges or similar:

```yaml
eventPublishing:
  topicMapping:
    "agent.output.invoice.processed":
      topic: "invoice.events"
      routing_key: "invoice.processed.success"
    
    "agent.error.processing":
      topic: "agent.errors"
      routing_key: "error.processing"
```

## Handler Event Type Declaration

Handlers declare which event types they publish. The routing configuration (topics and routing keys) is managed entirely through environment configuration.

### Declaring Event Types

```python
from base.src.handler import EventHandler

class InvoiceHandler(EventHandler):
    def get_published_event_types(self):
        """Declare event types this handler publishes."""
        return (
            "agent.output.invoice.processed",  # Success event type
            "agent.error.invoice.processing"    # Error event type
        )
```

### Why Separate Declaration from Configuration?

**Benefits:**
- **Separation of Concerns** - Developers declare event types, ops configure routing
- **Environment Flexibility** - Different routing per environment (dev/staging/prod)
- **No Code Changes** - Update routing without redeploying code
- **Centralized Configuration** - All routing rules in one place
- **Testability** - Test handlers without worrying about routing details

**Example:** Same handler code, different routing per environment:

```yaml
# Development
eventPublishing:
  topicMapping:
    "agent.output.invoice.processed":
      topic: "dev.invoice.events"
      routing_key: "invoice.processed"

# Production
eventPublishing:
  topicMapping:
    "agent.output.invoice.processed":
      topic: "prod.invoice.events"
      routing_key: "invoice.processed.priority.high"
```

## RabbitMQ Topic Exchange Routing

When using RabbitMQ topic exchanges, routing keys enable powerful pattern-based routing:

### Example Routing Patterns

```yaml
# Consumers can subscribe with patterns:
# - "invoice.#" - All invoice events
# - "invoice.processed.*" - All processed invoice events
# - "*.error.*" - All error events
# - "#.success" - All success events

eventPublishing:
  topicMapping:
    "agent.output.invoice.processed":
      topic: "invoice.events"
      routing_key: "invoice.processed.success"
    
    "agent.output.invoice.validated":
      topic: "invoice.events"
      routing_key: "invoice.validated.success"
    
    "agent.error.invoice.processing":
      topic: "invoice.events"
      routing_key: "invoice.error.processing"
```

### Consumer Binding Examples

```python
# Consumer 1: All invoice events
queue.bind(exchange="invoice.events", routing_key="invoice.#")

# Consumer 2: Only successful processing
queue.bind(exchange="invoice.events", routing_key="invoice.processed.success")

# Consumer 3: All errors
queue.bind(exchange="invoice.events", routing_key="invoice.error.#")

# Consumer 4: All success events
queue.bind(exchange="invoice.events", routing_key="*.*.success")
```

## Publishing Events Programmatically

### Using EventPublishingService

```python
from base.src.services import EventPublishingService

# Publish with explicit routing key
await publishing_service.publish_event(
    event_type="agent.output.invoice.processed",
    data={"invoice_id": "123", "amount": 1000},
    topic="invoice.events",
    routing_key="invoice.processed.success"
)

# Publish using configuration (routing key from config)
await publishing_service.publish_event(
    event_type="agent.output.invoice.processed",
    data={"invoice_id": "123", "amount": 1000}
)
```

## Dapr Metadata

Routing keys are passed to Dapr as metadata headers:

```http
POST /v1.0/publish/pubsub/invoice.events
Content-Type: application/cloudevents+json
metadata.routingKey: invoice.processed.success

{
  "specversion": "1.0",
  "type": "agent.output.invoice.processed",
  "source": "/agent/invoice-service",
  "id": "uuid",
  "data": { ... }
}
```

## Best Practices

### 1. Hierarchical Routing Keys

Use dot-separated hierarchical keys for flexible pattern matching:

```
<domain>.<action>.<status>
invoice.processed.success
invoice.validated.success
invoice.error.processing
document.classified.invoice
document.error.classification
```

### 2. Consistent Naming

Establish naming conventions for your team:

```
# Good
invoice.processed.success
invoice.validated.success
invoice.error.processing

# Avoid
invoice_processed
InvoiceSuccess
processed-invoice
```

### 3. Handler Responsibility

Handlers declare event types, configuration handles routing:

- ✅ Handler declares what event types it produces
- ✅ Configuration maps event types to topics/routing keys
- ✅ Clear separation between code and configuration
- ❌ Don't hardcode topics or routing keys in handlers

### 4. Configuration Management

All routing configuration in `values.yaml`:

```python
# In handler - just declare event types
def get_published_event_types(self):
    return (
        "agent.output.invoice.processed",
        "agent.error.invoice.processing"
    )
```

```yaml
# In values.yaml - configure routing
eventPublishing:
  topicMapping:
    "agent.output.invoice.processed":
      topic: "invoice.events"
      routing_key: "invoice.processed.success"
    "agent.error.invoice.processing":
      topic: "invoice.errors"
      routing_key: "invoice.error.processing"
```

## Migration Guide

### From Simple Topics to Routing Keys

**Before:**
```yaml
eventPublishing:
  topicMapping:
    "agent.output.invoice": "invoice-processed"
    "agent.error.invoice": "invoice-errors"
```

**After:**
```yaml
eventPublishing:
  topicMapping:
    "agent.output.invoice":
      topic: "invoice.events"
      routing_key: "invoice.processed"
    
    "agent.error.invoice":
      topic: "invoice.events"
      routing_key: "invoice.error"
```

### Backward Compatibility

The system supports both formats:

```yaml
# Old format still works
"agent.status.started": "agent.status"

# New format with routing keys
"agent.output.invoice":
  topic: "invoice.events"
  routing_key: "invoice.processed"
```

## Troubleshooting

### Routing Key Not Applied

**Symptom:** Events published without routing key

**Solution:** Check that:
1. Dapr pubsub component supports metadata
2. RabbitMQ exchange is type "topic"
3. Routing key is properly configured

### Events Not Reaching Consumers

**Symptom:** Published events not received by consumers

**Solution:** Verify:
1. Consumer binding pattern matches routing key
2. Exchange type is "topic" not "fanout"
3. Queue is bound to the exchange
4. Routing key format matches pattern

### Debug Logging

Enable debug logging to see routing configuration:

```python
import logging
logging.getLogger("base.src.services.event_publishing_service").setLevel(logging.DEBUG)
```

## Examples

See `docs/examples/handler_with_routing_keys.py` for complete working examples.

## Next Steps

Now that you understand event routing:

1. **[Creating Handlers](handlers.md)** - Implement handlers with custom routing
2. **[Building LLM Agents](llm-agents.md)** - Add AI capabilities
3. **[Testing Guide](testing.md)** - Test event routing

## References

- [RabbitMQ Topic Exchange Tutorial](https://www.rabbitmq.com/tutorials/tutorial-five-python.html)
- [Dapr Pub/Sub Metadata](https://docs.dapr.io/reference/api/pubsub_api/)
- [CloudEvents Specification](https://cloudevents.io/)

---

**Previous:** [Setting Up Events](events-setup.md) | **Next:** [Creating Handlers](handlers.md)
