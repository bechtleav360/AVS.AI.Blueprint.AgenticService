# Dapr Configuration

This directory contains Dapr component and subscription configurations for the agent blueprint.

## Files

- **`pubsub.yaml`** - RabbitMQ pub/sub component configuration
- **`subscriptions.yaml`** - Event subscriptions configuration
- **`secrets.yaml`** - Kubernetes secrets for sensitive data (example)

## Quick Start

### 1. Local Development (Dapr CLI)

Place these files in your Dapr components directory:

```bash
# Copy to Dapr components directory
mkdir -p ~/.dapr/components
cp pubsub.yaml ~/.dapr/components/
cp subscriptions.yaml ~/.dapr/components/

# Run with Dapr
dapr run \
  --app-id agent-blueprint \
  --app-port 8000 \
  --dapr-http-port 3500 \
  --dapr-grpc-port 50001 \
  --components-path ~/.dapr/components \
  -- python -m uvicorn custom.src.main:app --host 0.0.0.0 --port 8000
```

### 2. Kubernetes Deployment

Apply the configurations to your cluster:

```bash
# Apply pub/sub component
kubectl apply -f pubsub.yaml

# Apply subscriptions
kubectl apply -f subscriptions.yaml

# Verify
kubectl get components
kubectl get subscriptions
```

## Configuration Details

### Pub/Sub Component (`pubsub.yaml`)

Configures RabbitMQ as the message broker:

```yaml
apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: rabbitmq-pubsub
spec:
  type: pubsub.rabbitmq
  version: v1
  metadata:
    - name: host
      value: "amqp://localhost:5672"
    - name: vhost
      value: "bios"
```

**Key Settings:**
- `host` - RabbitMQ connection string
- `vhost` - Virtual host name
- `durable` - Persist messages to disk
- `autoAck` - Auto-acknowledge messages (set to false for manual ack)
- `prefetchCount` - Number of messages to prefetch

### Subscriptions (`subscriptions.yaml`)

Defines which topics the agent subscribes to:

```yaml
apiVersion: dapr.io/v2alpha1
kind: Subscription
metadata:
  name: invoice-processing-subscription
spec:
  topic: invoice.created
  route: /events/invoice
  pubsubname: rabbitmq-pubsub
```

**Key Settings:**
- `topic` - Topic name to subscribe to
- `route` - API endpoint to send events to
- `pubsubname` - Must match the component name
- `metadata.queueName` - RabbitMQ queue name
- `scopes` - Which apps can use this subscription

## Subscription Examples

### Basic Subscription

```yaml
apiVersion: dapr.io/v2alpha1
kind: Subscription
metadata:
  name: my-subscription
spec:
  topic: my.topic
  route: /events/my-topic
  pubsubname: rabbitmq-pubsub
  scopes:
    - agent-blueprint
```

### With Dead Letter Queue

```yaml
apiVersion: dapr.io/v2alpha1
kind: Subscription
metadata:
  name: invoice-validation-subscription
spec:
  topic: invoice.validate
  route: /events/validate
  pubsubname: rabbitmq-pubsub
  deadLetterTopic: invoice.validate.deadletter
  scopes:
    - agent-blueprint
```

### Bulk Subscription

```yaml
apiVersion: dapr.io/v2alpha1
kind: Subscription
metadata:
  name: bulk-subscription
spec:
  topic: invoice.*
  route: /events/bulk
  pubsubname: rabbitmq-pubsub
  bulkSubscribe:
    enabled: true
    maxMessagesCount: 100
    maxAwaitDurationMs: 1000
  scopes:
    - agent-blueprint
```

### With Custom Metadata

```yaml
apiVersion: dapr.io/v2alpha1
kind: Subscription
metadata:
  name: custom-subscription
spec:
  topic: my.topic
  route: /events/custom
  pubsubname: rabbitmq-pubsub
  metadata:
    - name: queueName
      value: my-custom-queue
    - name: durable
      value: "true"
    - name: autoDelete
      value: "false"
    - name: prefetchCount
      value: "20"
    - name: consumerTag
      value: "my-consumer"
  scopes:
    - agent-blueprint
```

## Routing Events to Handlers

The subscriptions route to FastAPI endpoints that trigger the handler chain:

```python
# In your custom REST API (custom/src/api/rest.py)
@router.post("/events/invoice")
async def handle_invoice_event(event: CloudEvent):
    """Handle invoice.created events."""
    result = await processing_service.process_event(event)
    return result

@router.post("/events/document")
async def handle_document_event(event: CloudEvent):
    """Handle document.uploaded events."""
    result = await processing_service.process_event(event)
    return result
```

The handler chain then processes the event:

```python
# Handler determines which runtime to use
class AgentInvokerHandler(EventHandler):
    async def can_handle_event(self, event, context):
        return event.data.details.get("action") == "invoke_agent"
    
    async def handle_event(self, event, context):
        context["invoice_text"] = event.data.invoice_text
        return None
    
    def get_runtime_name(self, event, context):
        return "invoice_analyzer"  # Route to specific runtime
```

## Environment-Specific Configuration

### Development

```yaml
# pubsub.yaml
metadata:
  - name: host
    value: "amqp://localhost:5672"
  - name: vhost
    value: "bios"
```

### Production

```yaml
# pubsub.yaml
metadata:
  - name: host
    secretKeyRef:
      name: rabbitmq-secret
      key: host
  - name: vhost
    value: "bios-prod"
```

Create the secret:
```bash
kubectl create secret generic rabbitmq-secret \
  --from-literal=host='amqp://user:pass@rabbitmq.prod:5672'
```

## Testing Subscriptions

### Publish a Test Message

```bash
# Using Dapr CLI
dapr publish \
  --publish-app-id agent-blueprint \
  --pubsub rabbitmq-pubsub \
  --topic invoice.created \
  --data '{"invoice_id": "INV-001", "amount": 100.00}'
```

### Using curl

```bash
# Publish via Dapr HTTP API
curl -X POST http://localhost:3500/v1.0/publish/rabbitmq-pubsub/invoice.created \
  -H "Content-Type: application/json" \
  -d '{
    "specversion": "1.0",
    "type": "invoice.created",
    "source": "test",
    "id": "test-001",
    "data": {
      "invoice_id": "INV-001",
      "amount": 100.00
    }
  }'
```

### Check Logs

```bash
# Dapr sidecar logs
kubectl logs -l app=agent-blueprint -c daprd

# Application logs
kubectl logs -l app=agent-blueprint -c agent-blueprint
```

## Troubleshooting

### Subscription Not Working

1. **Check component is loaded:**
   ```bash
   kubectl get components
   dapr components -k
   ```

2. **Check subscription is registered:**
   ```bash
   kubectl get subscriptions
   ```

3. **Verify route exists:**
   ```bash
   curl http://localhost:8000/docs
   # Check if /events/invoice endpoint exists
   ```

4. **Check Dapr logs:**
   ```bash
   kubectl logs -l app=agent-blueprint -c daprd
   ```

### Messages Not Being Received

1. **Check RabbitMQ connection:**
   ```bash
   # Access RabbitMQ management UI
   kubectl port-forward svc/rabbitmq 15672:15672
   # Open http://localhost:15672
   ```

2. **Verify queue exists:**
   - Check RabbitMQ management UI
   - Look for queue name from subscription

3. **Check message format:**
   - Must be CloudEvent format
   - Verify content-type header

### Dead Letter Queue

If messages fail processing, they go to the dead letter queue:

```yaml
deadLetterTopic: invoice.validate.deadletter
```

Create a subscription for the DLQ:
```yaml
apiVersion: dapr.io/v2alpha1
kind: Subscription
metadata:
  name: invoice-dlq-subscription
spec:
  topic: invoice.validate.deadletter
  route: /events/deadletter
  pubsubname: rabbitmq-pubsub
```

## Best Practices

1. **Use durable queues in production:**
   ```yaml
   metadata:
     - name: durable
       value: "true"
   ```

2. **Set appropriate prefetch counts:**
   ```yaml
   metadata:
     - name: prefetchCount
       value: "10"  # Adjust based on processing time
   ```

3. **Use dead letter queues:**
   ```yaml
   deadLetterTopic: my.topic.deadletter
   ```

4. **Scope subscriptions:**
   ```yaml
   scopes:
     - agent-blueprint  # Only this app can use it
   ```

5. **Use secrets for credentials:**
   ```yaml
   metadata:
     - name: host
       secretKeyRef:
         name: rabbitmq-secret
         key: host
   ```

## See Also

- [Dapr Pub/Sub Documentation](https://docs.dapr.io/developing-applications/building-blocks/pubsub/)
- [RabbitMQ Component Spec](https://docs.dapr.io/reference/components-reference/supported-pubsub/setup-rabbitmq/)
- [Subscription Spec](https://docs.dapr.io/reference/resource-specs/subscription-schema/)
