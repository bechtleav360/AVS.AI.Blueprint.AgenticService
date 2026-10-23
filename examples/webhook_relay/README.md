# Webhook Relay

A non-LLM event processing example that demonstrates how to use the Blueprint Agents
framework for pure event-driven workflows. The service receives incoming webhooks from
various sources (GitHub, Stripe, or generic HTTP), normalizes them into a standard
format, applies content filtering, enriches metadata, and publishes standardized
events over NATS.

## Architecture

One handler, one service -- the shape every Blueprint agent follows:

| Component | Responsibility |
|---|---|
| `WebhookHandler` | Routes `webhook.received` (envelope only), extracts the `WebhookPayload` DTO, turns it into an `IncomingWebhook` domain value and calls `WebhookService.relay()` **once**. Translates the answer into a result. |
| `WebhookService.relay()` | Every decision: duplicate? (cache), normalise per source, content filter (GitHub bots, Stripe test events), enrich (priority score, timestamp), record for dedup and the recent list. |

The handler's results:

- `HandlerResult(event_type="webhook.processed", ...)` -- relayed and enriched.
- `HandlerResult(event_type="webhook.filtered", ...)` -- dropped by a content rule, with the reason.
- `HandlerResult.skipped(reason)` -- a duplicate: nothing to do, acknowledged, logged at INFO.

## Event Flow

```
POST /api/webhooks
      |
      v
[webhook.received]  -->  WebhookHandler  -->  WebhookService.relay()
                                                 |
                       duplicate  <--------------+--> filtered -> [webhook.filtered]  -> webhooks-filtered
                       (skipped)                 |
                                                 +--> processed -> [webhook.processed] -> webhooks-processed
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
   uvicorn src.main:create_app --factory --host 0.0.0.0 --port 8000 --reload
   ```

### Without NATS (handlers still execute, publishing is a no-op)

```bash
pip install -e .
uvicorn src.main:create_app --factory --host 0.0.0.0 --port 8000 --reload
```

The handler and service process events locally. Published events will log a warning
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
      dto.py             # DTO: WebhookPayload (REST body and event data)
      domain_models.py   # Domain: IncomingWebhook, NormalizedEvent, RelayOutcome
    handlers/
      webhook_handler.py # webhook.received -> WebhookService.relay()
    services/
      webhook_service.py # Business logic and caching
    api/
      routes.py          # REST endpoints
  tests/
    test_handlers.py
    test_webhook_service.py
```
