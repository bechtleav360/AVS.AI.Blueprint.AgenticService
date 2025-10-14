# Agent Blueprint Helm Chart

This Helm chart deploys the Agent Blueprint application with Dapr sidecar, including ConfigMaps for prompts and settings, multi-runtime support, and auto-scaling.

## Prerequisites

- Kubernetes 1.19+
- Helm 3.2.0+
- Dapr 1.10+ installed on the cluster
- RabbitMQ (or configure a different pub/sub component)

## Installing Dapr

If Dapr is not installed on your cluster:

```bash
# Install Dapr CLI
wget -q https://raw.githubusercontent.com/dapr/cli/master/install/install.sh -O - | /bin/bash

# Initialize Dapr on Kubernetes
dapr init -k

# Verify installation
dapr status -k
```

## Installing the Chart

### 1. Create Secrets

First, create the required secrets:

```bash
# AI Model API key
kubectl create secret generic ai-model-secret \
  --from-literal=openai_api_key='sk-proj-your-key-here' \
  --from-literal=vllm_api_key='your-vllm-key' \
  --from-literal=vllm_base_url='https://your-vllm-server.com/v1'

# RabbitMQ credentials (if using external RabbitMQ)
kubectl create secret generic rabbitmq-secret \
  --from-literal=host='amqp://user:pass@rabbitmq:5672' \
  --from-literal=username='user' \
  --from-literal=password='pass'

# Data Gateway credentials (optional)
kubectl create secret generic data-gateway-secret \
  --from-literal=api_key='your-gateway-key' \
  --from-literal=base_url='https://gateway.example.com'
```

### 2. Install the Chart

```bash
# Add the repository (if published)
helm repo add agent-blueprint https://your-helm-repo.com
helm repo update

# Install with default values
helm install my-agent agent-blueprint/agent-blueprint

# Or install from local directory
helm install my-agent ./agent-blueprint

# Install with custom values
helm install my-agent ./agent-blueprint -f my-values.yaml
```

### 3. Verify Installation

```bash
# Check deployment
kubectl get pods -l app.kubernetes.io/name=agent-blueprint

# Check Dapr components
kubectl get components

# Check subscriptions
kubectl get subscriptions

# Check logs
kubectl logs -l app.kubernetes.io/name=agent-blueprint -c agent-blueprint
kubectl logs -l app.kubernetes.io/name=agent-blueprint -c daprd
```

## Configuration

### Basic Configuration

Create a `my-values.yaml` file:

```yaml
# Basic settings
replicaCount: 3

image:
  repository: your-registry/agent-blueprint
  tag: "v1.0.0"

app:
  environment: production
  logLevel: INFO
  
  aiModel:
    provider: openai
    name: gpt-4
    maxTokens: 2000
    temperature: 0.1

# Enable ingress
ingress:
  enabled: true
  className: nginx
  hosts:
    - host: agent.example.com
      paths:
        - path: /
          pathType: Prefix
```

### Multi-Runtime Configuration

Enable and configure multiple runtimes:

```yaml
runtimes:
  invoiceAnalyzer:
    enabled: true
    systemPromptName: invoice_system
    instructionPromptName: invoice_instruction
    aiModelName: gpt-4
    aiModelTemperature: 0.1
    aiModelMaxTokens: 2000
  
  documentClassifier:
    enabled: true
    systemPromptName: classifier_system
    instructionPromptName: classifier_instruction
    aiModelName: gpt-4
    aiModelTemperature: 0.0
    aiModelMaxTokens: 500
  
  summarizer:
    enabled: true
    systemPromptName: summarizer_system
    instructionPromptName: summarizer_instruction
    aiModelName: gpt-4
    aiModelTemperature: 0.7
    aiModelMaxTokens: 1500
```

### Custom Prompts

Override default prompts:

```yaml
prompts:
  invoiceSystem: |
    You are a specialized invoice processing AI.
    Your custom instructions here...
  
  invoiceInstruction: |
    Extract invoice data from:
    
    {invoice_text}
    
    Your custom extraction instructions...
```

### Dapr Subscriptions

Configure event subscriptions:

```yaml
subscriptions:
  invoiceCreated:
    enabled: true
    topic: invoice.created
    route: /events/invoice
    queueName: invoice-processing-queue
    prefetchCount: 10
  
  documentUploaded:
    enabled: true
    topic: document.uploaded
    route: /events/document
    queueName: document-classification-queue
    prefetchCount: 5
```

### Resource Limits

Adjust resources:

```yaml
resources:
  requests:
    cpu: 1000m
    memory: 1Gi
  limits:
    cpu: 4000m
    memory: 4Gi

autoscaling:
  enabled: true
  minReplicas: 3
  maxReplicas: 20
  targetCPUUtilizationPercentage: 70
```

## Upgrading

```bash
# Upgrade with new values
helm upgrade my-agent ./agent-blueprint -f my-values.yaml

# Upgrade with new image
helm upgrade my-agent ./agent-blueprint \
  --set image.tag=v1.1.0

# Rollback if needed
helm rollback my-agent
```

## Uninstalling

```bash
# Uninstall the release
helm uninstall my-agent

# Clean up secrets (if needed)
kubectl delete secret ai-model-secret rabbitmq-secret data-gateway-secret
```

## Examples

### Example 1: Development Environment

```yaml
# dev-values.yaml
replicaCount: 1

app:
  environment: development
  logLevel: DEBUG
  
  aiModel:
    provider: openai
    name: gpt-3.5-turbo

autoscaling:
  enabled: false

ingress:
  enabled: false

dapr:
  logLevel: debug
```

Deploy:
```bash
helm install my-agent ./agent-blueprint -f dev-values.yaml
```

### Example 2: Production with High Availability

```yaml
# prod-values.yaml
replicaCount: 5

image:
  repository: prod-registry/agent-blueprint
  tag: "v1.0.0"
  pullPolicy: Always

app:
  environment: production
  logLevel: WARNING
  
  aiModel:
    provider: openai
    name: gpt-4
    maxTokens: 2000
  
  observability:
    otelEnabled: true
    otelEndpoint: "http://otel-collector.observability:4317"

resources:
  requests:
    cpu: 2000m
    memory: 2Gi
  limits:
    cpu: 4000m
    memory: 4Gi

autoscaling:
  enabled: true
  minReplicas: 5
  maxReplicas: 20
  targetCPUUtilizationPercentage: 60

ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/rate-limit: "100"
  hosts:
    - host: agent.prod.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: agent-tls
      hosts:
        - agent.prod.example.com

affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          labelSelector:
            matchExpressions:
              - key: app.kubernetes.io/name
                operator: In
                values:
                  - agent-blueprint
          topologyKey: kubernetes.io/hostname
```

Deploy:
```bash
helm install my-agent ./agent-blueprint -f prod-values.yaml
```

### Example 3: Multiple Environments with Namespaces

```bash
# Development
kubectl create namespace dev
helm install agent-dev ./agent-blueprint \
  -n dev \
  -f dev-values.yaml

# Staging
kubectl create namespace staging
helm install agent-staging ./agent-blueprint \
  -n staging \
  -f staging-values.yaml

# Production
kubectl create namespace production
helm install agent-prod ./agent-blueprint \
  -n production \
  -f prod-values.yaml
```

## Testing

### Test the Deployment

```bash
# Port forward to test locally
kubectl port-forward svc/my-agent-agent-blueprint 8000:8000

# Test health endpoint
curl http://localhost:8000/health

# Test API docs
open http://localhost:8000/docs
```

### Test Dapr Pub/Sub

```bash
# Publish a test message
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl -X POST http://my-agent-agent-blueprint:3500/v1.0/publish/rabbitmq-pubsub/invoice.created \
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

# Check logs
kubectl logs -l app.kubernetes.io/name=agent-blueprint -c agent-blueprint --tail=50
```

## Troubleshooting

### Pods Not Starting

```bash
# Check pod status
kubectl get pods -l app.kubernetes.io/name=agent-blueprint

# Describe pod
kubectl describe pod <pod-name>

# Check events
kubectl get events --sort-by='.lastTimestamp'
```

### Dapr Sidecar Issues

```bash
# Check Dapr sidecar logs
kubectl logs <pod-name> -c daprd

# Check Dapr components
kubectl get components
kubectl describe component rabbitmq-pubsub

# Check Dapr operator
kubectl logs -n dapr-system -l app=dapr-operator
```

### Subscription Not Working

```bash
# Check subscriptions
kubectl get subscriptions
kubectl describe subscription <subscription-name>

# Verify route exists
kubectl exec -it <pod-name> -c agent-blueprint -- \
  curl http://localhost:8000/docs

# Check RabbitMQ
kubectl port-forward svc/rabbitmq 15672:15672
# Open http://localhost:15672
```

### ConfigMap Not Loading

```bash
# Check ConfigMaps
kubectl get configmaps
kubectl describe configmap my-agent-agent-blueprint-prompts
kubectl describe configmap my-agent-agent-blueprint-settings

# Verify mount
kubectl exec -it <pod-name> -c agent-blueprint -- \
  ls -la /etc/agent/prompts
kubectl exec -it <pod-name> -c agent-blueprint -- \
  cat /app/custom/settings.toml
```

## Parameters

### Global Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `replicaCount` | Number of replicas | `2` |
| `image.repository` | Image repository | `your-registry/agent-blueprint` |
| `image.tag` | Image tag | `latest` |
| `image.pullPolicy` | Image pull policy | `IfNotPresent` |

### Dapr Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `dapr.enabled` | Enable Dapr sidecar | `true` |
| `dapr.appId` | Dapr app ID | `agent-blueprint` |
| `dapr.appPort` | Application port | `8000` |
| `dapr.logLevel` | Dapr log level | `info` |

### Application Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `app.environment` | Environment name | `production` |
| `app.logLevel` | Application log level | `INFO` |
| `app.aiModel.provider` | AI provider | `openai` |
| `app.aiModel.name` | Model name | `gpt-4` |

### Runtime Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `runtimes.invoiceAnalyzer.enabled` | Enable invoice analyzer | `true` |
| `runtimes.documentClassifier.enabled` | Enable classifier | `true` |
| `runtimes.summarizer.enabled` | Enable summarizer | `false` |

See `values.yaml` for complete list of parameters.

## License

Copyright © 2025 Agent Blueprint Team
