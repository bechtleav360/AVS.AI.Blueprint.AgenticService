# Helm Chart Quick Start Guide

This guide will help you deploy the Agent Blueprint with Dapr in under 10 minutes.

## Choose Your Deployment Approach

The Agent Blueprint supports two deployment approaches:

1. **[With Dapr Operator](docs/installation-with-operator.md)** (Recommended)
   - Automatic sidecar injection
   - Kubernetes-native components
   - Production-ready
   - Requires cluster-admin

2. **[Without Dapr Operator](docs/installation-without-operator.md)** (Standalone)
   - Manual sidecar configuration
   - No cluster dependencies
   - Works in restricted environments
   - No cluster-admin required

**Not sure which to choose?** See the [Deployment Approaches Guide](docs/deployment-approaches.md) for a detailed comparison.

---

## Quick Start: With Dapr Operator

This is the recommended approach for most deployments.

### Prerequisites

- Kubernetes cluster (minikube, kind, or cloud provider)
- kubectl configured
- Helm 3 installed
- Cluster-admin permissions

### Step 1: Install Dapr (if not already installed)

```bash
# Install Dapr CLI
wget -q https://raw.githubusercontent.com/dapr/cli/master/install/install.sh -O - | /bin/bash

# Initialize Dapr on Kubernetes
dapr init -k

# Wait for Dapr to be ready
kubectl wait --for=condition=ready pod -l app=dapr-operator -n dapr-system --timeout=300s
```

## Step 2: Install RabbitMQ (if not already available)

```bash
# Add Bitnami repo
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update

# Install RabbitMQ
helm install rabbitmq bitnami/rabbitmq \
  --set auth.username=guest \
  --set auth.password=guest \
  --set service.type=ClusterIP

# Wait for RabbitMQ to be ready
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=rabbitmq --timeout=300s
```

## Step 3: Create Secrets

```bash
# Create AI Model secret
kubectl create secret generic ai-model-secret \
  --from-literal=openai_api_key='your-openai-key-here'

# Verify secret
kubectl get secret ai-model-secret
```

## Step 4: Install the Agent Blueprint

```bash
# Navigate to the helm chart directory
cd docs/deployment/helm

# Install with default values
helm install my-agent ./agent-blueprint

# Or with custom values
cat > my-values.yaml <<EOF
replicaCount: 2

image:
  repository: your-registry/agent-blueprint
  tag: latest

app:
  environment: development
  logLevel: DEBUG
  
  aiModel:
    provider: openai
    name: gpt-4

dapr:
  logLevel: debug

autoscaling:
  enabled: false
EOF

helm install my-agent ./agent-blueprint -f my-values.yaml
```

## Step 5: Verify Installation

```bash
# Check pods
kubectl get pods -l app.kubernetes.io/name=agent-blueprint

# Expected output:
# NAME                                READY   STATUS    RESTARTS   AGE
# my-agent-agent-blueprint-xxx-xxx    2/2     Running   0          1m

# Check Dapr components
kubectl get components

# Check subscriptions
kubectl get subscriptions

# Check logs
kubectl logs -l app.kubernetes.io/name=agent-blueprint -c agent-blueprint --tail=20
```

## Step 6: Test the Deployment

### Test Health Endpoint

```bash
# Port forward
kubectl port-forward svc/my-agent-agent-blueprint 8000:8000 &

# Test health
curl http://localhost:8000/health

# Expected output:
# {"status":"healthy","handlers":2,"runtimes":2}

# Open API docs
open http://localhost:8000/docs
```

### Test Dapr Pub/Sub

```bash
# Publish a test event
curl -X POST http://localhost:3500/v1.0/publish/rabbitmq-pubsub/invoice.created \
  -H "Content-Type: application/json" \
  -d '{
    "specversion": "1.0",
    "type": "invoice.created",
    "source": "test",
    "id": "test-001",
    "data": {
      "invoice_id": "INV-001",
      "amount": 100.00,
      "details": {
        "action": "invoke_agent"
      },
      "invoice_text": "Invoice #INV-001\nAmount: $100.00\nDate: 2025-01-15"
    }
  }'

# Check logs to see event processing
kubectl logs -l app.kubernetes.io/name=agent-blueprint -c agent-blueprint --tail=50 -f
```

## Step 7: Access the Application

### Option 1: Port Forward (Development)

```bash
kubectl port-forward svc/my-agent-agent-blueprint 8000:8000
# Access at http://localhost:8000
```

### Option 2: Enable Ingress (Production)

```bash
# Update values
cat > ingress-values.yaml <<EOF
ingress:
  enabled: true
  className: nginx
  hosts:
    - host: agent.local
      paths:
        - path: /
          pathType: Prefix
EOF

# Upgrade release
helm upgrade my-agent ./agent-blueprint -f ingress-values.yaml

# Add to /etc/hosts (for local testing)
echo "127.0.0.1 agent.local" | sudo tee -a /etc/hosts

# Access at http://agent.local
```

## Common Commands

```bash
# View all resources
kubectl get all -l app.kubernetes.io/name=agent-blueprint

# View logs
kubectl logs -l app.kubernetes.io/name=agent-blueprint -c agent-blueprint -f

# View Dapr logs
kubectl logs -l app.kubernetes.io/name=agent-blueprint -c daprd -f

# Describe deployment
kubectl describe deployment my-agent-agent-blueprint

# Get ConfigMaps
kubectl get configmap | grep agent-blueprint

# View prompts
kubectl get configmap my-agent-agent-blueprint-prompts -o yaml

# View settings
kubectl get configmap my-agent-agent-blueprint-settings -o yaml

# Scale manually
kubectl scale deployment my-agent-agent-blueprint --replicas=3

# Restart deployment
kubectl rollout restart deployment my-agent-agent-blueprint

# Check rollout status
kubectl rollout status deployment my-agent-agent-blueprint
```

## Troubleshooting

### Pods Not Starting

```bash
# Check pod status
kubectl get pods -l app.kubernetes.io/name=agent-blueprint

# Describe pod
kubectl describe pod <pod-name>

# Check logs
kubectl logs <pod-name> -c agent-blueprint
kubectl logs <pod-name> -c daprd
```

### Secret Not Found

```bash
# List secrets
kubectl get secrets

# Create missing secret
kubectl create secret generic ai-model-secret \
  --from-literal=openai_api_key='your-key'
```

### Dapr Component Issues

```bash
# Check Dapr components
kubectl get components
kubectl describe component rabbitmq-pubsub

# Check Dapr system
kubectl get pods -n dapr-system
```

## Cleanup

```bash
# Uninstall the release
helm uninstall my-agent

# Delete secrets
kubectl delete secret ai-model-secret

# Uninstall RabbitMQ (if installed for testing)
helm uninstall rabbitmq

# Uninstall Dapr (optional)
dapr uninstall -k
```

## Next Steps

1. **Customize Prompts** - Edit `values.yaml` to customize system and instruction prompts
2. **Add More Runtimes** - Enable additional runtimes in `values.yaml`
3. **Configure Monitoring** - Set up OpenTelemetry and metrics
4. **Production Setup** - Review the full README for production best practices
5. **CI/CD Integration** - Integrate Helm deployment into your CI/CD pipeline

## Quick Reference

```bash
# Install
helm install my-agent ./agent-blueprint

# Upgrade
helm upgrade my-agent ./agent-blueprint -f my-values.yaml

# Rollback
helm rollback my-agent

# Uninstall
helm uninstall my-agent

# List releases
helm list

# Get values
helm get values my-agent

# Test template rendering
helm template my-agent ./agent-blueprint

# Lint chart
helm lint ./agent-blueprint
```

## Support

For issues or questions:
- Check the full [README](agent-blueprint/README.md)
- Review [troubleshooting guide](agent-blueprint/README.md#troubleshooting)
- Check application logs
- Review Dapr documentation

---

## Quick Start: Without Dapr Operator (Standalone)

For restricted environments or when you don't have cluster-admin permissions.

### Prerequisites

- Kubernetes cluster
- kubectl configured
- Helm 3 installed
- **No cluster-admin required**

### Step 1: Create Secrets

```bash
# AI Model secret
kubectl create secret generic ai-model-secret \
  --from-literal=openai_api_key='sk-proj-your-key-here'

# RabbitMQ secret
kubectl create secret generic rabbitmq-secret \
  --from-literal=host='amqp://guest:guest@rabbitmq:5672'
```

### Step 2: Create Standalone Values

```bash
cat > standalone-values.yaml <<YAML
# Disable Dapr operator mode
dapr:
  enabled: false

# Enable standalone Dapr sidecar
daprStandalone:
  enabled: true
  image:
    repository: daprio/daprd
    tag: "1.12.0"
  appId: agent-blueprint
  appPort: 8000
  httpPort: 3500
  grpcPort: 50001
  logLevel: info

# Application config
image:
  repository: your-registry/agent-blueprint
  tag: latest

app:
  environment: production
  aiModel:
    provider: openai
    name: gpt-4

# Components as ConfigMaps
daprComponents:
  asConfigMaps: true
  rabbitmq:
    enabled: true
    existingSecret: rabbitmq-secret

# Subscriptions
subscriptions:
  mode: programmatic
  invoiceCreated:
    enabled: true
  documentUploaded:
    enabled: true
YAML
```

### Step 3: Install

```bash
# Install with standalone configuration
helm install my-agent ./agent-blueprint -f standalone-values.yaml

# Watch deployment
kubectl get pods -l app.kubernetes.io/name=agent-blueprint -w
```

### Step 4: Verify

```bash
# Check pods (should show 2/2: app + daprd)
kubectl get pods -l app.kubernetes.io/name=agent-blueprint

# Check logs
kubectl logs -l app.kubernetes.io/name=agent-blueprint -c agent-blueprint --tail=20
kubectl logs -l app.kubernetes.io/name=agent-blueprint -c daprd --tail=20

# Test health
kubectl port-forward svc/my-agent-agent-blueprint 8000:8000 &
curl http://localhost:8000/health
```

**For complete standalone setup:** See [Installation without Operator](docs/installation-without-operator.md)

---

## Documentation

### Getting Started
- **[Deployment Approaches](docs/deployment-approaches.md)** - Compare operator vs standalone
- **[Installation with Operator](docs/installation-with-operator.md)** - Full guide (recommended)
- **[Installation without Operator](docs/installation-without-operator.md)** - Standalone mode

### Advanced Topics
- **[Configuration Guide](docs/configuration.md)** - Customize your deployment
- **[Multi-Runtime Setup](docs/multi-runtime-setup.md)** - Configure multiple runtimes
- **[Production Best Practices](docs/production-best-practices.md)** - Production deployment
- **[Troubleshooting](docs/troubleshooting.md)** - Common issues and solutions

### Reference
- **[Chart README](agent-blueprint/README.md)** - Complete Helm chart documentation
- **[Values Reference](agent-blueprint/values.yaml)** - All configuration options

---

## Comparison

| Feature | With Operator | Without Operator |
|---------|--------------|------------------|
| Setup complexity | Medium | Low |
| Sidecar injection | Automatic | Manual |
| Cluster-admin required | Yes | No |
| Production-ready | Yes | Yes |
| Best for | Standard K8s | Restricted envs |

