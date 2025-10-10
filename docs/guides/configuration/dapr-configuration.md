# Dapr Configuration

**Complete guide to configuring Dapr for event-driven processing**

This guide covers all aspects of Dapr configuration including pub/sub components, subscriptions, and production settings.

## What is Dapr?

**Dapr** (Distributed Application Runtime) provides building blocks for microservices:
- **Pub/Sub** - Message broker abstraction
- **State Management** - Key-value storage
- **Service Invocation** - Service-to-service calls
- **Secrets Management** - Secure secret access

For the Agent Blueprint, we primarily use **Pub/Sub** for event processing.

## Directory Structure

```
custom/
├── dapr/
│   ├── components/              # Dapr components
│   │   ├── rabbitmq-pubsub.yaml
│   │   ├── redis-state.yaml    # Optional
│   │   └── secrets.yaml         # Optional
│   └── subscriptions/           # Event subscriptions
│       ├── invoice-events.yaml
│       └── asset-events.yaml
└── start_with_dapr.sh          # Startup script
```

## Pub/Sub Components

### RabbitMQ Component

**File:** `custom/dapr/components/rabbitmq-pubsub.yaml`

```yaml
apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: rabbitmq-pubsub
spec:
  type: pubsub.rabbitmq
  version: v1
  metadata:
    # Connection Settings
    - name: host
      value: "localhost:5672"
    - name: username
      value: "guest"
    - name: password
      value: "guest"
    - name: protocol
      value: "amqp"
    - name: vhost
      value: "/"
    
    # Queue Settings
    - name: durable
      value: "true"  # Queue survives broker restart
    - name: deletedWhenUnused
      value: "false"  # Keep queue even if no consumers
    - name: autoAck
      value: "false"  # Manual acknowledgment
    - name: deliveryMode
      value: "2"  # Persistent messages (saved to disk)
    - name: requeueInFailure
      value: "true"  # Retry failed messages
    
    # Performance Settings
    - name: prefetchCount
      value: "10"  # Process 10 messages at a time
    - name: reconnectWait
      value: "5s"  # Wait before reconnecting
    - name: concurrency
      value: "parallel"  # Process messages in parallel
    
    # Exchange Settings (optional)
    - name: exchangeKind
      value: "topic"  # topic, fanout, direct, headers
    - name: enableDeadLetter
      value: "true"  # Enable DLQ

scopes:
  - agent_blueprint  # Only this app can use this component
```

### Kafka Component

**File:** `custom/dapr/components/kafka-pubsub.yaml`

```yaml
apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: kafka-pubsub
spec:
  type: pubsub.kafka
  version: v1
  metadata:
    - name: brokers
      value: "localhost:9092"
    - name: consumerGroup
      value: "agent-blueprint-group"
    - name: clientID
      value: "agent-blueprint"
    - name: authType
      value: "none"  # or "password", "certificate"
    - name: maxMessageBytes
      value: "1024000"
    - name: consumeRetryInterval
      value: "200ms"
scopes:
  - agent_blueprint
```

### Azure Service Bus Component

**File:** `custom/dapr/components/servicebus-pubsub.yaml`

```yaml
apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: servicebus-pubsub
spec:
  type: pubsub.azure.servicebus
  version: v1
  metadata:
    - name: connectionString
      secretKeyRef:
        name: servicebus-secret
        key: connectionString
    - name: consumerID
      value: "agent-blueprint"
    - name: timeoutInSec
      value: "60"
    - name: maxDeliveryCount
      value: "10"
scopes:
  - agent_blueprint
```

## Component Settings Explained

### Connection Settings

| Setting | Description | Example |
|---------|-------------|---------|
| `host` | Broker address | `localhost:5672` |
| `username` | Authentication username | `guest` |
| `password` | Authentication password | `guest` |
| `protocol` | Connection protocol | `amqp`, `amqps` |
| `vhost` | Virtual host | `/` |

### Queue Settings

| Setting | Description | Values |
|---------|-------------|--------|
| `durable` | Queue survives restart | `true`, `false` |
| `deletedWhenUnused` | Auto-delete empty queue | `true`, `false` |
| `autoAck` | Auto-acknowledge messages | `true`, `false` |
| `deliveryMode` | Message persistence | `1` (transient), `2` (persistent) |
| `requeueInFailure` | Retry failed messages | `true`, `false` |

### Performance Settings

| Setting | Description | Recommended |
|---------|-------------|-------------|
| `prefetchCount` | Messages to fetch at once | Low: 1-5, Medium: 10-20, High: 50-100 |
| `reconnectWait` | Wait before reconnect | `5s` |
| `concurrency` | Processing mode | `parallel`, `serial` |

## Event Subscriptions

### Basic Subscription

**File:** `custom/dapr/subscriptions/invoice-events.yaml`

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
  
  # Metadata
  metadata:
    rawPayload: "false"  # Dapr wraps in CloudEvent format
  
  # Dead letter queue for failed messages
  deadLetterTopic: invoice.events.dlq
  
  # Bulk subscribe (optional)
  bulkSubscribe:
    enabled: false
    maxMessagesCount: 100
    maxAwaitDurationMs: 1000
```

### Subscription with Routing

Route different event types to different endpoints:

```yaml
apiVersion: dapr.io/v2alpha1
kind: Subscription
metadata:
  name: multi-route-subscription
spec:
  pubsubname: rabbitmq-pubsub
  topic: all.events
  routes:
    # Route based on CloudEvent type
    rules:
      - match: event.type == "invoice.created"
        path: /events/invoice
      - match: event.type == "asset.check"
        path: /events/asset
    default: /events/process
```

### Subscription with Filtering

Only receive specific events:

```yaml
apiVersion: dapr.io/v2alpha1
kind: Subscription
metadata:
  name: filtered-subscription
spec:
  pubsubname: rabbitmq-pubsub
  topic: invoice.events
  routes:
    default: /events/process
  
  # Only receive events matching these conditions
  scopes:
    - agent_blueprint
  
  metadata:
    # Custom filter (broker-specific)
    routingKey: "invoice.high-value.*"
```

### Multiple Subscriptions

Subscribe to multiple topics:

**invoice-events.yaml:**
```yaml
apiVersion: dapr.io/v2alpha1
kind: Subscription
metadata:
  name: invoice-subscription
spec:
  pubsubname: rabbitmq-pubsub
  topic: invoice.events
  routes:
    default: /events/process
  deadLetterTopic: invoice.events.dlq
```

**asset-events.yaml:**
```yaml
apiVersion: dapr.io/v2alpha1
kind: Subscription
metadata:
  name: asset-subscription
spec:
  pubsubname: rabbitmq-pubsub
  topic: asset.backup.check
  routes:
    default: /events/process
  deadLetterTopic: asset.events.dlq
```

## Secrets Management

### Using Kubernetes Secrets

**Component with secret reference:**

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
      value: "rabbitmq.prod.svc.cluster.local:5672"
    - name: username
      secretKeyRef:
        name: rabbitmq-secret
        key: username
    - name: password
      secretKeyRef:
        name: rabbitmq-secret
        key: password
```

**Create Kubernetes secret:**

```bash
kubectl create secret generic rabbitmq-secret \
  --from-literal=username=prod-user \
  --from-literal=password=prod-password \
  -n your-namespace
```

### Using Local Secrets Store

**File:** `custom/dapr/components/local-secrets.yaml`

```yaml
apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: local-secrets
spec:
  type: secretstores.local.file
  version: v1
  metadata:
    - name: secretsFile
      value: "/path/to/secrets.json"
```

**secrets.json:**
```json
{
  "rabbitmq-username": "guest",
  "rabbitmq-password": "guest"
}
```

## Production Configuration

### RabbitMQ Production Settings

```yaml
apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: rabbitmq-pubsub
spec:
  type: pubsub.rabbitmq
  version: v1
  metadata:
    # Connection
    - name: host
      value: "rabbitmq-cluster.prod.svc.cluster.local:5672"
    - name: username
      secretKeyRef:
        name: rabbitmq-secret
        key: username
    - name: password
      secretKeyRef:
        name: rabbitmq-secret
        key: password
    - name: protocol
      value: "amqps"  # TLS encryption
    
    # Reliability
    - name: durable
      value: "true"
    - name: autoAck
      value: "false"
    - name: deliveryMode
      value: "2"
    - name: requeueInFailure
      value: "true"
    
    # Performance
    - name: prefetchCount
      value: "20"  # Higher for production
    - name: reconnectWait
      value: "10s"
    - name: concurrency
      value: "parallel"
    
    # Dead Letter Queue
    - name: enableDeadLetter
      value: "true"
    - name: maxLen
      value: "10000"  # Max queue length
    - name: maxLenBytes
      value: "104857600"  # 100MB
    
    # TLS Settings
    - name: caCert
      secretKeyRef:
        name: rabbitmq-tls
        key: ca.crt
    - name: clientCert
      secretKeyRef:
        name: rabbitmq-tls
        key: client.crt
    - name: clientKey
      secretKeyRef:
        name: rabbitmq-tls
        key: client.key
```

### High Availability Setup

```yaml
metadata:
  - name: host
    value: "rabbitmq-0.rabbitmq.prod.svc.cluster.local:5672,rabbitmq-1.rabbitmq.prod.svc.cluster.local:5672,rabbitmq-2.rabbitmq.prod.svc.cluster.local:5672"
  - name: reconnectWait
    value: "5s"
  - name: maxReconnectAttempts
    value: "10"
```

## Running with Dapr

### Local Development

**Start script:** `custom/start_with_dapr.sh`

```bash
#!/bin/bash

cd "$(dirname "$0")"

dapr run \
  --app-id agent_blueprint \
  --app-port 8001 \
  --dapr-http-port 3500 \
  --dapr-grpc-port 50001 \
  --resources-path ./dapr/components \
  --log-level info \
  -- python -m uvicorn src.main:app --host 0.0.0.0 --port 8001
```

Make executable:
```bash
chmod +x custom/start_with_dapr.sh
```

Run:
```bash
cd custom
./start_with_dapr.sh
```

### Kubernetes Deployment

**Deployment with Dapr annotations:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agent-blueprint
spec:
  replicas: 3
  template:
    metadata:
      annotations:
        dapr.io/enabled: "true"
        dapr.io/app-id: "agent-blueprint"
        dapr.io/app-port: "8001"
        dapr.io/log-level: "info"
        dapr.io/config: "dapr-config"
    spec:
      containers:
      - name: agent
        image: agent-blueprint:latest
        ports:
        - containerPort: 8001
```

### Docker Compose

```yaml
version: '3.8'
services:
  agent:
    build: ./custom
    ports:
      - "8001:8001"
    environment:
      - AI_MODEL_API_KEY=${AI_MODEL_API_KEY}
    networks:
      - agent-network
  
  agent-dapr:
    image: "daprio/daprd:latest"
    command: [
      "./daprd",
      "-app-id", "agent_blueprint",
      "-app-port", "8001",
      "-dapr-http-port", "3500",
      "-dapr-grpc-port", "50001",
      "-components-path", "/components",
      "-log-level", "info"
    ]
    volumes:
      - ./custom/dapr/components:/components
    depends_on:
      - agent
    network_mode: "service:agent"
  
  rabbitmq:
    image: rabbitmq:3-management
    ports:
      - "5672:5672"
      - "15672:15672"
    networks:
      - agent-network

networks:
  agent-network:
```

## Publishing Events

### Via Dapr HTTP API

```bash
curl -X POST http://localhost:3500/v1.0/publish/rabbitmq-pubsub/invoice.events \
  -H "Content-Type: application/json" \
  -d '{
    "invoice_id": "INV-001",
    "amount": 100.00,
    "currency": "EUR"
  }'
```

### Via Python

```python
import httpx

async def publish_result(result: dict):
    """Publish result to RabbitMQ via Dapr."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:3500/v1.0/publish/rabbitmq-pubsub/invoice.results",
            json=result
        )
        response.raise_for_status()
```

### With CloudEvent Format

```python
from datetime import datetime
import uuid

async def publish_cloud_event(data: dict):
    """Publish CloudEvent via Dapr."""
    event = {
        "specversion": "1.0",
        "type": "invoice.processed",
        "source": "agent-blueprint",
        "id": str(uuid.uuid4()),
        "time": datetime.utcnow().isoformat() + "Z",
        "datacontenttype": "application/json",
        "data": data
    }
    
    async with httpx.AsyncClient() as client:
        await client.post(
            "http://localhost:3500/v1.0/publish/rabbitmq-pubsub/invoice.results",
            json=event
        )
```

## Monitoring and Debugging

### View Dapr Logs

```bash
# Local
dapr logs --app-id agent_blueprint

# Kubernetes
kubectl logs -l app=agent-blueprint -c daprd
```

### Check Component Status

```bash
# List components
curl http://localhost:3500/v1.0/metadata

# Check specific component
curl http://localhost:3500/v1.0/metadata | jq '.components[] | select(.name=="rabbitmq-pubsub")'
```

### Debug Subscriptions

```bash
# List subscriptions
curl http://localhost:3500/v1.0/metadata | jq '.subscriptions'
```

### Enable Debug Logging

```bash
dapr run \
  --app-id agent_blueprint \
  --log-level debug \
  -- python -m uvicorn src.main:app
```

## Troubleshooting

### Dapr Not Starting

**Check:**
1. Dapr installed: `dapr --version`
2. Dapr initialized: `dapr init`
3. Port not in use: `lsof -i :3500`

**Fix:**
```bash
dapr uninstall
dapr init
```

### Component Not Loading

**Check:**
1. YAML syntax: `yamllint custom/dapr/components/rabbitmq-pubsub.yaml`
2. File in correct directory
3. Dapr logs for errors

**Debug:**
```bash
dapr run --log-level debug --resources-path ./dapr/components -- echo "test"
```

### Messages Not Arriving

**Check:**
1. Subscription file exists
2. Topic name matches
3. Route endpoint correct
4. RabbitMQ connection working

**Test:**
```bash
# Publish test message
dapr publish --publish-app-id agent_blueprint \
  --pubsub rabbitmq-pubsub \
  --topic invoice.events \
  --data '{"test": true}'

# Check agent logs
```

### Connection Refused

**Check:**
1. RabbitMQ running: `docker ps | grep rabbitmq`
2. Port forwarding active: `lsof -i :5672`
3. Credentials correct

**Test connection:**
```bash
curl -u guest:guest http://localhost:15672/api/overview
```

## Best Practices

### 1. Use Secrets for Credentials

❌ **Bad:**
```yaml
- name: password
  value: "hardcoded-password"
```

✅ **Good:**
```yaml
- name: password
  secretKeyRef:
    name: rabbitmq-secret
    key: password
```

### 2. Enable Dead Letter Queues

```yaml
deadLetterTopic: invoice.events.dlq
```

Monitor and replay failed messages.

### 3. Use Appropriate Prefetch Count

- **Low latency:** `prefetchCount: 1-5`
- **High throughput:** `prefetchCount: 50-100`
- **Balanced:** `prefetchCount: 10-20`

### 4. Set Timeouts

```yaml
- name: requestTimeout
  value: "30s"
- name: reconnectWait
  value: "5s"
```

### 5. Use TLS in Production

```yaml
- name: protocol
  value: "amqps"
- name: caCert
  secretKeyRef:
    name: rabbitmq-tls
    key: ca.crt
```

## See Also

- [Agent Configuration](agent-configuration.md) - Configure your agent
- [Events Setup Guide](../events-setup.md) - Step-by-step setup
- [Architecture Overview](../architecture.md) - System design
