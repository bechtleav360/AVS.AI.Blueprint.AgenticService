# RabbitMQ Setup for Agent Blueprint

## Overview
Connected to RabbitMQ cluster running in Kubernetes (`dev-bios-bechtle` namespace) via port-forward.

## Connection Details

### Kubernetes Resources
- **Namespace**: `dev-bios-bechtle`
- **Service**: `rabbitmq` (ClusterIP: 172.30.30.62)
- **Pods**: 
  - `rabbitmq-server-0`
  - `rabbitmq-server-1`
  - `rabbitmq-server-2`
- **Ports**:
  - `5672` - AMQP
  - `15672` - Management UI
  - `15692` - Prometheus metrics

### Credentials
- **Username**: `default_user_gL_0b5UoGT7HlwnDWib`
- **Password**: `HJ7PBBqNljN4KWMsXOtQ97LPuqaX7pBb`
- **VHost**: `/`

### Connection String
```
amqp://default_user_gL_0b5UoGT7HlwnDWib:HJ7PBBqNljN4KWMsXOtQ97LPuqaX7pBb@localhost:5672/
```

## Setup Steps

### 1. Start Port Forward
```bash
kubectl port-forward -n dev-bios-bechtle svc/rabbitmq 5672:5672 15672:15672
```

Keep this running in a separate terminal.

### 2. Access Management UI
Open browser: http://localhost:15672
- Username: `default_user_gL_0b5UoGT7HlwnDWib`
- Password: `HJ7PBBqNljN4KWMsXOtQ97LPuqaX7pBb`

### 3. Verify Connection
```bash
# Test management API
curl -u "default_user_gL_0b5UoGT7HlwnDWib:HJ7PBBqNljN4KWMsXOtQ97LPuqaX7pBb" \
  http://localhost:15672/api/overview | jq .rabbitmq_version
```

Expected output: `"4.1.1"`

## Dapr Configuration

### Component File
Created: `custom/dapr/components/rabbitmq-pubsub.yaml`

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
      value: "localhost:5672"
    - name: username
      value: "default_user_gL_0b5UoGT7HlwnDWib"
    - name: password
      value: "HJ7PBBqNljN4KWMsXOtQ97LPuqaX7pBb"
    - name: protocol
      value: "amqp"
    - name: vhost
      value: "/"
    - name: durable
      value: "true"
    - name: deletedWhenUnused
      value: "false"
    - name: autoAck
      value: "false"
    - name: deliveryMode
      value: "2"
    - name: requeueInFailure
      value: "true"
    - name: prefetchCount
      value: "10"
    - name: reconnectWait
      value: "5s"
    - name: concurrency
      value: "parallel"
scopes:
  - agent_blueprint
```

### Start Service with Dapr

**Option 1: Use the start script (recommended)**
```bash
./custom/start_with_dapr.sh
```

**Option 2: Manual command**
```bash
cd custom
dapr run \
  --app-id agent_blueprint \
  --app-port 8001 \
  --dapr-http-port 3500 \
  --dapr-grpc-port 50001 \
  --resources-path ./dapr/components \
  --log-level info \
  -- .venv/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 8001
```

## Testing

### 1. Direct REST API Call
```bash
curl -X POST http://localhost:8001/api/process-resource \
  -H "Content-Type: application/json" \
  -d '{
    "invoice_text": "Invoice #INV-2025-001\nDate: 2025-01-15\nCustomer: Bechtle AG\n\nLine Items:\n1. Consulting services - Qty: 10 hrs @ 150.00 EUR/hr\n2. Software license - Qty: 1 @ 500.00 EUR\n\nSubtotal: 2000.00 EUR\nTax (19%): 380.00 EUR\nTotal: 2380.00 EUR",
    "details": {"action": "invoke_agent", "source": "curl_test"}
  }'
```

### 2. Publish via Dapr PubSub
```bash
curl -X POST http://localhost:3500/v1.0/publish/rabbitmq-pubsub/invoice.events \
  -H "Content-Type: application/json" \
  -d '{
    "invoice_text": "Invoice #TEST-001\nAmount: 100.00 EUR",
    "details": {"action": "invoke_agent", "source": "dapr_test"}
  }'
```

### 3. Check RabbitMQ Queues
```bash
curl -u "default_user_gL_0b5UoGT7HlwnDWib:HJ7PBBqNljN4KWMsXOtQ97LPuqaX7pBb" \
  http://localhost:15672/api/queues | jq '.[] | {name, messages}'
```

## RabbitMQ Cluster Status
- **Version**: 4.1.1
- **Erlang**: 27.3.4.1
- **Cluster**: 3 nodes (rabbitmq-server-0, rabbitmq-server-1, rabbitmq-server-2)
- **Current queues**: 6
- **Current connections**: 2
- **Current channels**: 2

## Environment Variables
Created `.env.rabbitmq` with connection details (not committed to git).

## Next Steps
1. ✅ Port-forward established
2. ✅ Dapr component configured
3. ✅ Connection verified via management API
4. ⏳ Test with vLLM tool-calling (requires `--tool-call-parser=hermes`)
5. ⏳ Integrate with agent runtime
6. ⏳ Test end-to-end flow: REST → Handler → Agent → Tool → Result

## Troubleshooting

### Port-forward dies
```bash
# Restart port-forward
kubectl port-forward -n dev-bios-bechtle svc/rabbitmq 5672:5672 15672:15672
```

### Check RabbitMQ pods
```bash
kubectl get pods -n dev-bios-bechtle | grep rabbit
kubectl logs -n dev-bios-bechtle rabbitmq-server-0
```

### Dapr component not loading
```bash
# Check Dapr logs
dapr logs --app-id agent_blueprint
```
