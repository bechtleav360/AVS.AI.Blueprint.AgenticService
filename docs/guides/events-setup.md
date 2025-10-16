# Setting Up Events with Dapr and RabbitMQ

**Time to complete:** 30 minutes  
**Difficulty:** Intermediate

This guide explains how to set up event-driven processing using Dapr and RabbitMQ.

## What Are Events?

**Events** are messages that tell your agent something happened. For example:
- "A new invoice was uploaded"
- "An asset needs backup verification"
- "A user requested processing"

Instead of constantly checking for work (polling), your agent **subscribes** to events and processes them as they arrive.

## Why Dapr?

**Dapr** (Distributed Application Runtime) is a framework that makes it easy to:
- Subscribe to events from RabbitMQ, Kafka, Azure Service Bus, etc.
- Publish results to other services
- Switch message brokers without changing your code

**Think of Dapr as a translator** between your agent and the message broker.

## Architecture Overview

```
┌─────────────┐         ┌──────┐         ┌──────────────┐
│  RabbitMQ   │ ◄─────► │ Dapr │ ◄─────► │  Your Agent  │
│  (Events)   │         │      │         │              │
└─────────────┘         └──────┘         └──────────────┘
```

1. **RabbitMQ** stores events in queues
2. **Dapr** pulls events from RabbitMQ
3. **Your Agent** processes events via HTTP callbacks
4. **Dapr** publishes results back to RabbitMQ

## Prerequisites

- Completed [Getting Started Guide](getting-started.md)
- Access to a RabbitMQ instance
- Dapr CLI installed

### Install Dapr CLI

**macOS/Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/dapr/cli/master/install/install.sh | /bin/bash
```

**Windows (PowerShell):**
```powershell
iwr -useb https://raw.githubusercontent.com/dapr/cli/master/install/install.ps1 | iex
```

Verify:
```bash
dapr --version
```

### Initialize Dapr

```bash
dapr init
```

This installs Dapr runtime components locally.

## Step 1: Connect to RabbitMQ

### Option A: Use Kubernetes RabbitMQ (Production)

If you have a RabbitMQ cluster in Kubernetes:

```bash
# Port-forward to access RabbitMQ
kubectl port-forward -n dev-bios-bechtle svc/rabbitmq 5672:5672 15672:15672
```

Keep this running in a separate terminal.

### Option B: Run RabbitMQ Locally (Development)

```bash
docker run -d --name rabbitmq \
  -p 5672:5672 \
  -p 15672:15672 \
  -e RABBITMQ_DEFAULT_USER=guest \
  -e RABBITMQ_DEFAULT_PASS=guest \
  rabbitmq:3-management
```

### Verify Connection

Access the management UI:
- **URL:** http://localhost:15672
- **Username:** `guest` (or your credentials)
- **Password:** `guest` (or your credentials)

You should see the RabbitMQ dashboard.

## Step 2: Configure Dapr Component

Create a Dapr component file that tells Dapr how to connect to RabbitMQ.

### Create Component Directory

```bash
mkdir -p custom/dapr/components
```

### Create RabbitMQ Component

Create `custom/dapr/components/rabbitmq-pubsub.yaml`:

```yaml
apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: rabbitmq-pubsub
spec:
  type: pubsub.rabbitmq
  version: v1
  metadata:
    # Connection settings
    - name: host
      value: "localhost:5672"
    - name: username
      value: "guest"  # Change for production!
    - name: password
      value: "guest"  # Use secrets in production!
    - name: protocol
      value: "amqp"
    - name: vhost
      value: "/"
    
    # Queue settings
    - name: durable
      value: "true"  # Queues survive broker restart
    - name: deletedWhenUnused
      value: "false"  # Keep queues even if no consumers
    - name: autoAck
      value: "false"  # Manual acknowledgment for reliability
    - name: deliveryMode
      value: "2"  # Persistent messages
    - name: requeueInFailure
      value: "true"  # Retry failed messages
    
    # Performance settings
    - name: prefetchCount
      value: "10"  # Process 10 messages at a time
    - name: reconnectWait
      value: "5s"  # Wait 5s before reconnecting
    - name: concurrency
      value: "parallel"  # Process messages in parallel

scopes:
  - agent_blueprint  # Only this app can use this component
```

**What do these settings mean?**

| Setting | Purpose |
|---------|---------|
| `durable: true` | Queue survives if RabbitMQ restarts |
| `autoAck: false` | Agent must confirm message processing |
| `deliveryMode: 2` | Messages are saved to disk |
| `requeueInFailure: true` | Failed messages go back to queue |
| `prefetchCount: 10` | Process 10 messages at once |

## Step 3: Create Event Subscription

Tell Dapr which events your agent wants to receive.

### Create Subscription File

Create `custom/dapr/subscriptions/invoice-events.yaml`:

```yaml
apiVersion: dapr.io/v2alpha1
kind: Subscription
metadata:
  name: invoice-events-subscription
spec:
  # Which pub/sub component to use
  pubsubname: rabbitmq-pubsub
  
  # Which topic to subscribe to
  topic: invoice.events
  
  # Where to send events (your agent's endpoint)
  routes:
    default: /events/process
  
  # Optional: Filter events
  # Only process events matching these rules
  metadata:
    rawPayload: "false"  # Dapr wraps events in CloudEvent format
  
  # Dead letter queue for failed messages
  deadLetterTopic: invoice.events.dlq
  
  # Bulk subscribe settings
  bulkSubscribe:
    enabled: false  # Process one message at a time
```

**What's happening here?**
- Your agent subscribes to `invoice.events` topic
- When a message arrives, Dapr sends it to `/events/process`
- If processing fails repeatedly, the message goes to the dead letter queue

### Multiple Subscriptions

You can subscribe to multiple topics:

```yaml
# custom/dapr/subscriptions/asset-events.yaml
apiVersion: dapr.io/v2alpha1
kind: Subscription
metadata:
  name: asset-events-subscription
spec:
  pubsubname: rabbitmq-pubsub
  topic: asset.backup.check
  routes:
    default: /events/process
```

## Step 4: Implement Event Handler

Your agent needs an endpoint to receive events from Dapr.

The base framework already provides `/events/process`, but let's understand how it works:

### Event Flow

```
1. RabbitMQ receives message
2. Dapr pulls message
3. Dapr converts to CloudEvent format
4. Dapr POSTs to /events/process
5. Your handler processes event
6. Handler returns success/failure
7. Dapr ACKs or NACKs message
```

### CloudEvent Format

Dapr sends events in CloudEvent format:

```json
{
  "specversion": "1.0",
  "type": "invoice.created",
  "source": "invoice-service",
  "id": "unique-id-123",
  "time": "2025-10-10T10:00:00Z",
  "datacontenttype": "application/json",
  "data": {
    "invoice_id": "INV-001",
    "amount": 100.00
  }
}
```

### Create Handler

In `custom/src/agent/handlers.py`:

```python
class InvoiceEventHandler(EventHandler):
    """Processes invoice events from RabbitMQ."""
    
    def __init__(self):
        super().__init__("InvoiceEventHandler", priority=10)
    
    async def _can_handle(self, event: CloudEvent, context: dict) -> bool:
        """Handle invoice.created events."""
        return event.type == "invoice.created"
    
    async def _handle(self, event: CloudEvent, context: dict):
        """Process the invoice."""
        invoice_data = event.data
        logger.info("Processing invoice: %s", invoice_data.get("invoice_id"))
        
        # Your processing logic here
        context["use_agent"] = True
        context["invoice_data"] = invoice_data
        
        return None  # Let agent runtime handle it
```

### Register Handler

In `custom/src/main.py`:

```python
from .agent.handlers import InvoiceEventHandler

app = (
    AppBuilder()
    .with_handler(InvoiceEventHandler)  # Add this line
    .with_agent_runtime(AgentRuntime, is_default=True)
    .build()
)
```

## Step 5: Run with Dapr

### Create Start Script

Create `custom/start_with_dapr.sh`:

```bash
#!/bin/bash

# Start your agent with Dapr sidecar
dapr run \
  --app-id agent_blueprint \
  --app-port 8001 \
  --dapr-http-port 3500 \
  --dapr-grpc-port 50001 \
  --resources-path ./dapr/components \
  --log-level info \
  -- python -m uvicorn src.main:app --host 0.0.0.0 --port 8001
```

Make it executable:
```bash
chmod +x custom/start_with_dapr.sh
```

### Start Your Agent

```bash
cd custom
./start_with_dapr.sh
```

You should see:
```
INFO[0000] Starting Dapr with id agent_blueprint
INFO[0000] Dapr sidecar is up and running
```

## Step 6: Test Event Processing

### Publish Test Event

Use Dapr CLI to publish a test event:

```bash
dapr publish \
  --publish-app-id agent_blueprint \
  --pubsub rabbitmq-pubsub \
  --topic invoice.events \
  --data '{
    "invoice_id": "INV-TEST-001",
    "amount": 100.00,
    "currency": "EUR"
  }'
```

### Via HTTP

You can also publish via Dapr's HTTP API:

```bash
curl -X POST http://localhost:3500/v1.0/publish/rabbitmq-pubsub/invoice.events \
  -H "Content-Type: application/json" \
  -d '{
    "invoice_id": "INV-TEST-002",
    "amount": 250.00,
    "currency": "EUR"
  }'
```

### Check Logs

Watch your agent logs - you should see:
```
INFO - Processing invoice: INV-TEST-001
INFO - Agent processing completed
```

### Check RabbitMQ

Open http://localhost:15672 and check:
- **Queues** tab - see your subscription queue
- **Messages** - see message rates
- **Connections** - see Dapr connected

## Step 7: Publish Results

After processing, publish results back to RabbitMQ.

### In Your Handler

```python
async def _handle(self, event: CloudEvent, context: dict):
    # Process event
    result = await self.process_invoice(event.data)
    
    # Publish result
    await self.publish_result(result)
    
    return result

async def publish_result(self, result: dict):
    """Publish result to RabbitMQ via Dapr."""
    import httpx
    
    async with httpx.AsyncClient() as client:
        await client.post(
            "http://localhost:3500/v1.0/publish/rabbitmq-pubsub/invoice.results",
            json=result
        )
```

## Configuration Reference

### Common Settings

```yaml
# Reliable delivery
autoAck: false
deliveryMode: 2
durable: true
requeueInFailure: true

# Performance
prefetchCount: 10      # Low: 1-5, Medium: 10-20, High: 50-100
concurrency: parallel  # or "serial" for ordered processing

# Retry behavior
reconnectWait: 5s      # How long to wait before reconnecting
```

### Production Settings

For production, use secrets:

```yaml
metadata:
  - name: host
    secretKeyRef:
      name: rabbitmq-secret
      key: host
  - name: username
    secretKeyRef:
      name: rabbitmq-secret
      key: username
  - name: password
    secretKeyRef:
      name: rabbitmq-secret
      key: password
```

## Troubleshooting

### Dapr Can't Connect to RabbitMQ

**Check:**
1. Is RabbitMQ running? `docker ps | grep rabbitmq`
2. Is port-forward active? `lsof -i :5672`
3. Are credentials correct in component file?

**Test connection:**
```bash
curl -u guest:guest http://localhost:15672/api/overview
```

### Events Not Arriving

**Check:**
1. Is subscription file in `dapr/subscriptions/`?
2. Is topic name correct?
3. Is route endpoint correct?

**View Dapr logs:**
```bash
dapr logs --app-id agent_blueprint
```

### Messages Going to Dead Letter Queue

**Reasons:**
- Handler throws exception
- Handler returns error status
- Processing timeout

**Check DLQ:**
```bash
# List queues
curl -u guest:guest http://localhost:15672/api/queues

# Get messages from DLQ
curl -u guest:guest http://localhost:15672/api/queues/%2F/invoice.events.dlq/get \
  -d '{"count":10,"ackmode":"ack_requeue_false","encoding":"auto"}'
```

### High Memory Usage

**Solutions:**
- Reduce `prefetchCount`
- Use `concurrency: serial`
- Add rate limiting

## Best Practices

### 1. Use Idempotent Handlers

Process the same event multiple times safely:

```python
async def _handle(self, event: CloudEvent, context: dict):
    event_id = event.id
    
    # Check if already processed
    if await self.is_processed(event_id):
        logger.info("Event %s already processed, skipping", event_id)
        return {"status": "duplicate"}
    
    # Process event
    result = await self.process(event.data)
    
    # Mark as processed
    await self.mark_processed(event_id)
    
    return result
```

### 2. Handle Failures Gracefully

```python
async def _handle(self, event: CloudEvent, context: dict):
    try:
        return await self.process(event.data)
    except RetryableError as e:
        # Let Dapr retry
        logger.warning("Retryable error: %s", e)
        raise
    except PermanentError as e:
        # Don't retry, log and move on
        logger.error("Permanent error: %s", e)
        return {"status": "failed", "error": str(e)}
```

### 3. Monitor Performance

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

async def _handle(self, event: CloudEvent, context: dict):
    with tracer.start_as_current_span("process_invoice") as span:
        span.set_attribute("invoice.id", event.data.get("invoice_id"))
        
        result = await self.process(event.data)
        
        span.set_attribute("result.status", result["status"])
        return result
```

## Next Steps

Now that you have event processing set up:

1. **[Event Routing](event-routing.md)** - Configure topics and routing keys for advanced message routing
2. **[Create Custom Handlers](handlers.md)** - Build domain-specific processors
3. **[Build LLM Agents](llm-agents.md)** - Add AI capabilities
4. **[Testing Guide](testing.md)** - Test event processing

## Quick Reference

```bash
# Start with Dapr
cd custom && ./start_with_dapr.sh

# Publish test event
dapr publish --publish-app-id agent_blueprint \
  --pubsub rabbitmq-pubsub \
  --topic invoice.events \
  --data '{"test": true}'

# View Dapr logs
dapr logs --app-id agent_blueprint

# Check RabbitMQ
curl -u guest:guest http://localhost:15672/api/overview
```

---

**Next:** [Creating Handlers](handlers.md) →
