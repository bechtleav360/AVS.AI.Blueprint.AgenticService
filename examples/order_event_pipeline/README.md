# Order Event Pipeline

An e-commerce order processing pipeline built with the Blueprint Agents framework,
demonstrating Dapr pub/sub event processing with a handler chain-of-responsibility pattern.

## Overview

This example shows how to build an event-driven order processing system where:

1. An `order.created` CloudEvent arrives via Dapr pub/sub.
2. The **OrderValidationHandler** (priority 10) validates the order payload. If
   validation fails it publishes an `order.rejected` event and short-circuits the
   chain. If the order is valid it passes control to the next handler.
3. The **OrderEnrichmentHandler** (priority 20) enriches valid orders with tax
   calculations, shipping estimates, and timestamps, then publishes an
   `order.validated` event.
4. A REST API exposes cached order statuses for querying.

```
order.created --> [ValidationHandler] --invalid--> order.rejected
                        |
                      valid
                        |
                        v
                 [EnrichmentHandler] --> order.validated
```

## Project Structure

```
order_event_pipeline/
  settings.toml          # Dynaconf configuration
  pyproject.toml         # Package metadata
  src/
    main.py              # Application entry point
    models/
      schemas.py         # Pydantic data models
    handlers/
      order_validation_handler.py
      order_enrichment_handler.py
    services/
      order_service.py   # Business logic (validation, enrichment)
    api/
      routes.py          # REST endpoints for querying orders
  tests/
    test_handlers.py
    test_order_service.py
```

## Running

### With Dapr

```bash
dapr run --app-id order-pipeline --app-port 8000 -- uvicorn src.main:app --host 0.0.0.0 --port 8000
```

### Without Dapr (development mode)

Set `event_bus = ""` in `settings.toml` to disable Dapr integration, then run:

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

The handler chain still processes events submitted via the REST API, but no
pub/sub publishing occurs.

## Example CloudEvent Payload

Publish the following CloudEvent to the Dapr pubsub topic to trigger processing:

```json
{
  "specversion": "1.0",
  "id": "evt-001",
  "type": "order.created",
  "source": "/services/storefront",
  "subject": "order-12345",
  "time": "2026-03-30T10:00:00Z",
  "datacontenttype": "application/json",
  "data": {
    "order_id": "order-12345",
    "customer_id": "cust-42",
    "items": [
      {
        "product_id": "prod-001",
        "name": "Wireless Keyboard",
        "quantity": 2,
        "unit_price": 49.99
      }
    ],
    "shipping_address": "123 Main St, Springfield, IL 62704",
    "total_amount": 99.98
  }
}
```

## Configuration

All settings live in `settings.toml` and are loaded by Dynaconf. Key sections:

| Section                              | Purpose                                    |
|--------------------------------------|--------------------------------------------|
| `default`                            | App name, port, environment, log level     |
| `default.event_publishing`           | Default pubsub name for Dapr               |
| `default.event_publishing.topic_mapping` | Maps event types to Dapr topics        |
| `default.cache`                      | Disk cache directory, size limit, TTL      |
