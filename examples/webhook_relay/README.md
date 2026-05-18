# Webhook Relay

A non-LLM event processing example that demonstrates how to use the Blueprint Agents
framework for pure event-driven workflows. The service receives incoming webhooks from
various sources (GitHub, Stripe, or generic HTTP), normalizes them into a standard
format, applies content filtering, enriches metadata, and publishes standardized
events over NATS.

## Architecture

The processing pipeline is built as a **handler chain** with three stages:

| Priority | Handler              | Responsibility                                      |
|----------|----------------------|-----------------------------------------------------|
| 5        | WebhookNormalizer    | Parse raw payload, deduplicate, normalize structure  |
| 10       | ContentFilter        | Drop bot events, test events, and other noise        |
| 15       | MetadataEnricher     | Add priority scores, timestamps, publish final event |

Lower priority numbers execute first. Each handler can:

- Return `None` to pass the event to the next handler in the chain.
- Return a `HandlerResult` to publish an event and stop processing.

## Event Flow

```
POST /api/webhooks
      |
      v
[webhook.received]  -->  WebhookNormalizer (5)
                              |
                              v  (stores normalized_event in context)
                         ContentFilter (10)
                              |
                              v  (filters bots / test events)
                         MetadataEnricher (15)
                              |
                              v
                    [webhook.processed]  -->  NATS topic: webhooks-processed
                    [webhook.filtered]   -->  NATS topic: webhooks-filtered
```

## NATS Configuration

The service uses NATS as its event bus. Topic mapping is configured in
`settings.toml`:

```toml
[default]
event_bus = "nats"
nats_url = "nats://localhost:4222"

[default.event_publishing.topic_mapping]
"webhook.processed" = { topic = "webhooks-processed" }
"webhook.filtered"  = { topic = "webhooks-filtered" }
```

## Running

### With NATS (full event publishing)

1. Start a local NATS server:

   ```bash
   docker run -d --name nats -p 4222:4222 nats:latest
   ```

2. Install and run:

   ```bash
   pip install -e .
   uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
   ```

### Without NATS (handlers still execute, publishing is a no-op)

```bash
pip install -e .
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

The handler chain processes events locally. Published events will log a warning
if NATS is unreachable but will not crash the service.

### Testing the endpoint

```bash
# GitHub push event
curl -X POST http://localhost:8000/api/webhooks \
  -H "Content-Type: application/json" \
  -d '{
    "source": "github",
    "event_type": "push",
    "payload": {
      "action": "completed",
      "sender": {"login": "octocat"},
      "repository": {"full_name": "octocat/Hello-World"}
    }
  }'

# Stripe payment event
curl -X POST http://localhost:8000/api/webhooks \
  -H "Content-Type: application/json" \
  -d '{
    "source": "stripe",
    "event_type": "payment_intent.succeeded",
    "payload": {
      "type": "payment_intent.succeeded",
      "object": "payment_intent",
      "id": "pi_123"
    }
  }'

# List recent webhooks
curl http://localhost:8000/api/webhooks/recent
```

## Project Structure

```
webhook_relay/
  settings.toml          # Application configuration
  pyproject.toml         # Python packaging
  src/
    main.py              # AppBuilder wiring
    models/
      schemas.py         # Pydantic models
    handlers/
      webhook_normalizer.py
      content_filter.py
      metadata_enricher.py
    services/
      webhook_service.py # Business logic and caching
    api/
      routes.py          # REST endpoints
  tests/
    test_handlers.py
    test_webhook_service.py
```
