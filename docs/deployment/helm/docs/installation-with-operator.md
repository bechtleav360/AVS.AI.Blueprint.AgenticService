# Installation with Dapr Operator

This guide covers deploying the Agent Blueprint with the Dapr operator (recommended approach).

## Prerequisites

- Kubernetes 1.19+
- Helm 3.2.0+
- kubectl configured
- Cluster-admin permissions

## Step 1: Install Dapr on Kubernetes

### Using Dapr CLI (Recommended)

```bash
# Install Dapr CLI
wget -q https://raw.githubusercontent.com/dapr/cli/master/install/install.sh -O - | /bin/bash

# Verify CLI installation
dapr version

# Initialize Dapr on Kubernetes
dapr init -k

# Wait for Dapr to be ready
kubectl wait --for=condition=ready pod \
  -l app=dapr-operator \
  -n dapr-system \
  --timeout=300s

# Verify Dapr installation
dapr status -k
```

Expected output:
```
NAME                   NAMESPACE    HEALTHY  STATUS   REPLICAS  VERSION  AGE  CREATED
dapr-sentry            dapr-system  True     Running  1         1.12.0   1m   2024-01-15 10:00.00
dapr-operator          dapr-system  True     Running  1         1.12.0   1m   2024-01-15 10:00.00
dapr-sidecar-injector  dapr-system  True     Running  1         1.12.0   1m   2024-01-15 10:00.00
dapr-placement-server  dapr-system  True     Running  1         1.12.0   1m   2024-01-15 10:00.00
```

### Using Helm (Alternative)

```bash
# Add Dapr Helm repo
helm repo add dapr https://dapr.github.io/helm-charts/
helm repo update

# Install Dapr
helm upgrade --install dapr dapr/dapr \
  --version=1.12 \
  --namespace dapr-system \
  --create-namespace \
  --wait

# Verify installation
kubectl get pods -n dapr-system
```

## Step 2: Install RabbitMQ (Optional)

If you don't have RabbitMQ available:

```bash
# Add Bitnami repo
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update

# Install RabbitMQ
helm install rabbitmq bitnami/rabbitmq \
  --set auth.username=guest \
  --set auth.password=guest \
  --set service.type=ClusterIP \
  --set replicaCount=1

# Wait for RabbitMQ to be ready
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/name=rabbitmq \
  --timeout=300s

# Get RabbitMQ connection details
export RABBITMQ_PASSWORD=$(kubectl get secret rabbitmq -o jsonpath="{.data.rabbitmq-password}" | base64 -d)
echo "RabbitMQ Password: $RABBITMQ_PASSWORD"
```

## Step 3: Create Secrets

### AI Model Secret

```bash
# OpenAI
kubectl create secret generic ai-model-secret \
  --from-literal=openai_api_key='sk-proj-your-openai-key-here'

# Or vLLM
kubectl create secret generic ai-model-secret \
  --from-literal=vllm_api_key='your-vllm-key' \
  --from-literal=vllm_base_url='https://your-vllm-server.com/v1'

# Or both
kubectl create secret generic ai-model-secret \
  --from-literal=openai_api_key='sk-proj-...' \
  --from-literal=vllm_api_key='...' \
  --from-literal=vllm_base_url='https://...'
```

### RabbitMQ Secret (if using external RabbitMQ)

```bash
kubectl create secret generic rabbitmq-secret \
  --from-literal=host='amqp://user:password@rabbitmq.external:5672'
```

### Data Gateway Secret (Optional)

```bash
kubectl create secret generic data-gateway-secret \
  --from-literal=api_key='your-gateway-api-key' \
  --from-literal=base_url='https://gateway.example.com'
```

### Verify Secrets

```bash
kubectl get secrets
kubectl describe secret ai-model-secret
```

## Step 4: Install Agent Blueprint

### Basic Installation

```bash
# Navigate to helm directory
cd docs/deployment/helm

# Install with default values
helm install my-agent ./agent-blueprint

# Watch deployment
kubectl get pods -l app.kubernetes.io/name=agent-blueprint -w
```

### Installation with Custom Values

```bash
# Create custom values file
cat > my-values.yaml <<EOF
replicaCount: 3

image:
  repository: your-registry/agent-blueprint
  tag: v1.0.0
  pullPolicy: IfNotPresent

app:
  environment: production
  logLevel: INFO
  
  aiModel:
    provider: openai
    name: gpt-4
    maxTokens: 2000
    temperature: 0.1

dapr:
  logLevel: info

runtimes:
  invoiceAnalyzer:
    enabled: true
  documentClassifier:
    enabled: true
  summarizer:
    enabled: false

autoscaling:
  enabled: true
  minReplicas: 3
  maxReplicas: 10
EOF

# Install with custom values
helm install my-agent ./agent-blueprint -f my-values.yaml
```

## Step 5: Verify Installation

### Check Pods

```bash
# List pods
kubectl get pods -l app.kubernetes.io/name=agent-blueprint

# Expected output (2/2 means app + daprd sidecar):
# NAME                                READY   STATUS    RESTARTS   AGE
# my-agent-agent-blueprint-xxx-xxx    2/2     Running   0          1m
# my-agent-agent-blueprint-yyy-yyy    2/2     Running   0          1m

# Describe pod to see Dapr sidecar
kubectl describe pod <pod-name>
```

### Check Dapr Components

```bash
# List components
kubectl get components

# Expected output:
# NAME              AGE
# rabbitmq-pubsub   1m

# Describe component
kubectl describe component rabbitmq-pubsub
```

### Check Subscriptions

```bash
# List subscriptions
kubectl get subscriptions

# Expected output:
# NAME                                      AGE
# my-agent-agent-blueprint-invoice-created  1m
# my-agent-agent-blueprint-document-uploaded 1m

# Describe subscription
kubectl describe subscription my-agent-agent-blueprint-invoice-created
```

### Check ConfigMaps

```bash
# List ConfigMaps
kubectl get configmaps | grep agent-blueprint

# View prompts
kubectl get configmap my-agent-agent-blueprint-prompts -o yaml

# View settings
kubectl get configmap my-agent-agent-blueprint-settings -o yaml
```

### Check Logs

```bash
# Application logs
kubectl logs -l app.kubernetes.io/name=agent-blueprint -c agent-blueprint --tail=50

# Dapr sidecar logs
kubectl logs -l app.kubernetes.io/name=agent-blueprint -c daprd --tail=50

# Follow logs
kubectl logs -l app.kubernetes.io/name=agent-blueprint -c agent-blueprint -f
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
# Publish a test event via Dapr HTTP API
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
kubectl logs -l app.kubernetes.io/name=agent-blueprint -c agent-blueprint --tail=50
```

### Test from Another Pod

```bash
# Create a test pod
kubectl run test-pod --image=curlimages/curl -it --rm --restart=Never -- sh

# Inside the pod, publish an event
curl -X POST http://my-agent-agent-blueprint:3500/v1.0/publish/rabbitmq-pubsub/invoice.created \
  -H "Content-Type: application/json" \
  -d '{"data": {"invoice_id": "INV-002"}}'
```

## Step 7: Configure Ingress (Optional)

### Enable Ingress

```bash
# Create ingress values
cat > ingress-values.yaml <<EOF
ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - host: agent.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: agent-tls
      hosts:
        - agent.example.com
EOF

# Upgrade with ingress
helm upgrade my-agent ./agent-blueprint -f ingress-values.yaml
```

### Verify Ingress

```bash
# Check ingress
kubectl get ingress

# Test ingress
curl https://agent.example.com/health
```

## Upgrading

### Upgrade Application

```bash
# Upgrade with new image
helm upgrade my-agent ./agent-blueprint \
  --set image.tag=v1.1.0 \
  --reuse-values

# Upgrade with new values file
helm upgrade my-agent ./agent-blueprint -f my-values.yaml

# Check rollout status
kubectl rollout status deployment my-agent-agent-blueprint
```

### Upgrade Dapr

```bash
# Upgrade Dapr using CLI
dapr upgrade -k --runtime-version 1.13.0

# Or using Helm
helm upgrade dapr dapr/dapr \
  --version=1.13 \
  --namespace dapr-system \
  --reuse-values
```

## Scaling

### Manual Scaling

```bash
# Scale up
kubectl scale deployment my-agent-agent-blueprint --replicas=5

# Scale down
kubectl scale deployment my-agent-agent-blueprint --replicas=2
```

### Auto-scaling

Auto-scaling is enabled by default in the Helm chart:

```yaml
autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
  targetMemoryUtilizationPercentage: 80
```

Check HPA status:
```bash
kubectl get hpa
kubectl describe hpa my-agent-agent-blueprint
```

## Monitoring

### Dapr Dashboard

```bash
# Install Dapr dashboard
dapr dashboard -k

# Access at http://localhost:8080
```

### Prometheus Metrics

```bash
# Dapr exposes metrics on port 9090
kubectl port-forward <pod-name> 9090:9090

# Access metrics
curl http://localhost:9090/metrics
```

### Distributed Tracing

If OpenTelemetry is configured:

```bash
# Check traces in your tracing backend
# (Jaeger, Zipkin, etc.)
```

## Troubleshooting

### Pods Not Starting

```bash
# Check pod status
kubectl get pods -l app.kubernetes.io/name=agent-blueprint

# Describe pod
kubectl describe pod <pod-name>

# Check events
kubectl get events --sort-by='.lastTimestamp' | grep agent-blueprint
```

### Dapr Sidecar Not Injected

```bash
# Verify Dapr operator is running
kubectl get pods -n dapr-system

# Check pod annotations
kubectl get pod <pod-name> -o jsonpath='{.metadata.annotations}'

# Verify sidecar injector
kubectl logs -n dapr-system -l app=dapr-sidecar-injector
```

### Component Not Working

```bash
# Check component status
kubectl get component rabbitmq-pubsub -o yaml

# Check Dapr operator logs
kubectl logs -n dapr-system -l app=dapr-operator

# Test component directly
kubectl exec -it <pod-name> -c daprd -- \
  curl http://localhost:3500/v1.0/metadata
```

### Subscription Not Receiving Events

```bash
# Check subscription
kubectl describe subscription <subscription-name>

# Check RabbitMQ
kubectl port-forward svc/rabbitmq 15672:15672
# Open http://localhost:15672 (guest/guest)

# Check Dapr logs
kubectl logs <pod-name> -c daprd | grep subscription
```

## Uninstalling

### Uninstall Application

```bash
# Uninstall Helm release
helm uninstall my-agent

# Verify pods are terminated
kubectl get pods -l app.kubernetes.io/name=agent-blueprint
```

### Uninstall Dapr (Optional)

```bash
# Uninstall Dapr using CLI
dapr uninstall -k

# Or using Helm
helm uninstall dapr -n dapr-system

# Delete namespace
kubectl delete namespace dapr-system
```

### Clean Up Secrets

```bash
kubectl delete secret ai-model-secret
kubectl delete secret rabbitmq-secret
kubectl delete secret data-gateway-secret
```

## Next Steps

- [Configuration Guide](configuration.md)
- [Multi-Runtime Setup](multi-runtime-setup.md)
- [Production Best Practices](production-best-practices.md)
- [Troubleshooting Guide](troubleshooting.md)
