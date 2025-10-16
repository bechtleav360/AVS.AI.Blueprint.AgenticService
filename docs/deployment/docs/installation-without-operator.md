# Installation without Dapr Operator

This guide covers deploying the Agent Blueprint with Dapr in standalone mode (without the operator).

## Prerequisites

- Kubernetes 1.19+
- Helm 3.2.0+
- kubectl configured
- **No cluster-admin permissions required**

## Overview

In this mode:
- Dapr sidecar is manually defined as a container
- Components are configured via ConfigMaps
- Subscriptions are handled programmatically or via ConfigMaps
- No Dapr control plane needed

## Step 1: Install RabbitMQ (Optional)

If you don't have RabbitMQ available:

```bash
# Add Bitnami repo
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update

# Install RabbitMQ
helm install rabbitmq bitnami/rabbitmq \
  --set auth.username=guest \
  --set auth.password=guest \
  --set service.type=ClusterIP

# Wait for RabbitMQ
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/name=rabbitmq \
  --timeout=300s
```

## Step 2: Create Secrets

### AI Model Secret

```bash
kubectl create secret generic ai-model-secret \
  --from-literal=openai_api_key='sk-proj-your-key-here'
```

### RabbitMQ Secret

```bash
kubectl create secret generic rabbitmq-secret \
  --from-literal=host='amqp://guest:guest@rabbitmq:5672'
```

## Step 3: Create Standalone Values File

Create a values file for standalone mode:

```bash
cat > standalone-values.yaml <<EOF
# Disable Dapr operator mode
dapr:
  enabled: false

# Enable standalone Dapr sidecar
daprStandalone:
  enabled: true
  image:
    repository: daprio/daprd
    tag: "1.12.0"
    pullPolicy: IfNotPresent
  
  # Dapr configuration
  appId: agent-blueprint
  appPort: 8000
  httpPort: 3500
  grpcPort: 50001
  metricsPort: 9090
  logLevel: info
  
  # Sidecar resources
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: 1000m
      memory: 512Mi

# Application configuration
replicaCount: 2

image:
  repository: your-registry/agent-blueprint
  tag: latest

app:
  environment: production
  logLevel: INFO
  
  aiModel:
    provider: openai
    name: gpt-4

# Components as ConfigMaps
daprComponents:
  asConfigMaps: true
  rabbitmq:
    enabled: true
    host: "amqp://rabbitmq:5672"
    vhost: "bios"
    existingSecret: "rabbitmq-secret"

# Subscriptions
subscriptions:
  mode: configmap  # or programmatic
  invoiceCreated:
    enabled: true
    topic: invoice.created
    route: /events/invoice
  documentUploaded:
    enabled: true
    topic: document.uploaded
    route: /events/document

# Runtimes
runtimes:
  invoiceAnalyzer:
    enabled: true
  documentClassifier:
    enabled: true
EOF
```

## Step 4: Update Helm Templates

The Helm chart needs templates for standalone mode. Create or update these templates:

### Deployment Template (with manual sidecar)

The deployment template should include logic for standalone mode:

```yaml
# templates/deployment.yaml (excerpt)
{{- if .Values.daprStandalone.enabled }}
# Dapr sidecar container
- name: daprd
  image: "{{ .Values.daprStandalone.image.repository }}:{{ .Values.daprStandalone.image.tag }}"
  imagePullPolicy: {{ .Values.daprStandalone.image.pullPolicy }}
  command:
    - "/daprd"
  args:
    - "--app-id"
    - {{ .Values.daprStandalone.appId | quote }}
    - "--app-port"
    - {{ .Values.daprStandalone.appPort | quote }}
    - "--dapr-http-port"
    - {{ .Values.daprStandalone.httpPort | quote }}
    - "--dapr-grpc-port"
    - {{ .Values.daprStandalone.grpcPort | quote }}
    - "--metrics-port"
    - {{ .Values.daprStandalone.metricsPort | quote }}
    - "--log-level"
    - {{ .Values.daprStandalone.logLevel | quote }}
    - "--components-path"
    - "/components"
    - "--config"
    - "/config/config.yaml"
  ports:
    - containerPort: {{ .Values.daprStandalone.httpPort }}
      name: dapr-http
      protocol: TCP
    - containerPort: {{ .Values.daprStandalone.grpcPort }}
      name: dapr-grpc
      protocol: TCP
    - containerPort: {{ .Values.daprStandalone.metricsPort }}
      name: metrics
      protocol: TCP
  volumeMounts:
    - name: dapr-components
      mountPath: /components
      readOnly: true
    - name: dapr-config
      mountPath: /config
      readOnly: true
  resources:
    {{- toYaml .Values.daprStandalone.resources | nindent 12 }}
{{- end }}
```

### ConfigMap for Dapr Components

```yaml
# templates/configmap-dapr-components.yaml
{{- if .Values.daprStandalone.enabled }}
{{- if .Values.daprComponents.asConfigMaps }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "agent-blueprint.fullname" . }}-dapr-components
  labels:
    {{- include "agent-blueprint.labels" . | nindent 4 }}
data:
  {{- if .Values.daprComponents.rabbitmq.enabled }}
  pubsub.yaml: |
    apiVersion: dapr.io/v1alpha1
    kind: Component
    metadata:
      name: rabbitmq-pubsub
    spec:
      type: pubsub.rabbitmq
      version: v1
      metadata:
        {{- if .Values.daprComponents.rabbitmq.existingSecret }}
        - name: host
          secretKeyRef:
            name: {{ .Values.daprComponents.rabbitmq.existingSecret }}
            key: host
        {{- else }}
        - name: host
          value: {{ .Values.daprComponents.rabbitmq.host | quote }}
        {{- end }}
        - name: vhost
          value: {{ .Values.daprComponents.rabbitmq.vhost | quote }}
        - name: durable
          value: "true"
        - name: autoAck
          value: "false"
        - name: deliveryMode
          value: "2"
        - name: prefetchCount
          value: "10"
  {{- end }}
{{- end }}
{{- end }}
```

### ConfigMap for Dapr Configuration

```yaml
# templates/configmap-dapr-config.yaml
{{- if .Values.daprStandalone.enabled }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "agent-blueprint.fullname" . }}-dapr-config
  labels:
    {{- include "agent-blueprint.labels" . | nindent 4 }}
data:
  config.yaml: |
    apiVersion: dapr.io/v1alpha1
    kind: Configuration
    metadata:
      name: dapr-config
    spec:
      tracing:
        samplingRate: "1"
        zipkin:
          endpointAddress: "http://zipkin:9411/api/v2/spans"
      metric:
        enabled: true
{{- end }}
```

## Step 5: Install the Chart

```bash
# Install with standalone configuration
helm install my-agent ./agent-blueprint -f standalone-values.yaml

# Watch deployment
kubectl get pods -l app.kubernetes.io/name=agent-blueprint -w
```

## Step 6: Verify Installation

### Check Pods

```bash
# List pods (should show 2/2: app + daprd)
kubectl get pods -l app.kubernetes.io/name=agent-blueprint

# Describe pod to see both containers
kubectl describe pod <pod-name>

# Check containers
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].name}'
# Expected: agent-blueprint daprd
```

### Check Dapr Sidecar

```bash
# Check Dapr version
kubectl exec -it <pod-name> -c daprd -- /daprd --version

# Check Dapr metadata
kubectl exec -it <pod-name> -c daprd -- \
  curl http://localhost:3500/v1.0/metadata
```

### Check Components

```bash
# List ConfigMaps
kubectl get configmap | grep dapr-components

# View component configuration
kubectl get configmap <name>-dapr-components -o yaml

# Verify component is loaded
kubectl exec -it <pod-name> -c daprd -- \
  curl http://localhost:3500/v1.0/metadata | jq '.components'
```

### Check Logs

```bash
# Application logs
kubectl logs -l app.kubernetes.io/name=agent-blueprint -c agent-blueprint --tail=50

# Dapr sidecar logs
kubectl logs -l app.kubernetes.io/name=agent-blueprint -c daprd --tail=50
```

## Step 7: Configure Subscriptions

### Option 1: Programmatic Subscriptions (Recommended)

The application handles subscriptions via code:

```python
# In your FastAPI app
@app.get("/dapr/subscribe")
async def subscribe():
    """Dapr subscription endpoint."""
    return [
        {
            "pubsubname": "rabbitmq-pubsub",
            "topic": "invoice.created",
            "route": "/events/invoice"
        },
        {
            "pubsubname": "rabbitmq-pubsub",
            "topic": "document.uploaded",
            "route": "/events/document"
        }
    ]
```

### Option 2: ConfigMap Subscriptions

Create a ConfigMap for subscriptions:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: dapr-subscriptions
data:
  subscriptions.yaml: |
    - pubsubname: rabbitmq-pubsub
      topic: invoice.created
      route: /events/invoice
      metadata:
        rawPayload: "false"
    - pubsubname: rabbitmq-pubsub
      topic: document.uploaded
      route: /events/document
```

Mount in deployment:
```yaml
volumeMounts:
  - name: dapr-subscriptions
    mountPath: /subscriptions
    readOnly: true

# Add to daprd args:
- "--resources-path"
- "/subscriptions"
```

## Step 8: Test the Deployment

### Test Health

```bash
# Port forward
kubectl port-forward svc/my-agent-agent-blueprint 8000:8000 &

# Test health
curl http://localhost:8000/health
```

### Test Dapr Pub/Sub

```bash
# Port forward Dapr HTTP port
kubectl port-forward <pod-name> 3500:3500 &

# Publish event
curl -X POST http://localhost:3500/v1.0/publish/rabbitmq-pubsub/invoice.created \
  -H "Content-Type: application/json" \
  -d '{
    "specversion": "1.0",
    "type": "invoice.created",
    "source": "test",
    "data": {
      "invoice_id": "INV-001",
      "details": {"action": "invoke_agent"},
      "invoice_text": "Test invoice"
    }
  }'

# Check logs
kubectl logs -l app.kubernetes.io/name=agent-blueprint -c agent-blueprint --tail=50
```

## Upgrading

### Upgrade Application

```bash
# Upgrade with new image
helm upgrade my-agent ./agent-blueprint \
  -f standalone-values.yaml \
  --set image.tag=v1.1.0

# Check rollout
kubectl rollout status deployment my-agent-agent-blueprint
```

### Upgrade Dapr Sidecar

```bash
# Update Dapr version in values
helm upgrade my-agent ./agent-blueprint \
  -f standalone-values.yaml \
  --set daprStandalone.image.tag=1.13.0

# Force pod restart
kubectl rollout restart deployment my-agent-agent-blueprint
```

## Scaling

```bash
# Manual scaling
kubectl scale deployment my-agent-agent-blueprint --replicas=5

# Update Helm values
helm upgrade my-agent ./agent-blueprint \
  -f standalone-values.yaml \
  --set replicaCount=5
```

## Monitoring

### Metrics

```bash
# Port forward metrics port
kubectl port-forward <pod-name> 9090:9090

# Access Dapr metrics
curl http://localhost:9090/metrics
```

### Logs

```bash
# Stream logs
kubectl logs -f <pod-name> -c daprd

# Filter logs
kubectl logs <pod-name> -c daprd | grep -i error
```

## Troubleshooting

### Sidecar Not Starting

```bash
# Check pod status
kubectl describe pod <pod-name>

# Check sidecar logs
kubectl logs <pod-name> -c daprd

# Check image pull
kubectl get events | grep <pod-name>
```

### Component Not Loading

```bash
# Check ConfigMap exists
kubectl get configmap <name>-dapr-components

# Check ConfigMap content
kubectl get configmap <name>-dapr-components -o yaml

# Check volume mount
kubectl describe pod <pod-name> | grep -A 5 "Mounts:"

# Check component in Dapr
kubectl exec -it <pod-name> -c daprd -- \
  curl http://localhost:3500/v1.0/metadata | jq '.components'
```

### Subscription Not Working

```bash
# Check subscription endpoint
kubectl exec -it <pod-name> -c agent-blueprint -- \
  curl http://localhost:8000/dapr/subscribe

# Check Dapr logs for subscription
kubectl logs <pod-name> -c daprd | grep subscription

# Test publish directly
kubectl exec -it <pod-name> -c daprd -- \
  curl -X POST http://localhost:3500/v1.0/publish/rabbitmq-pubsub/test.topic \
  -d '{"test": "data"}'
```

### RabbitMQ Connection Issues

```bash
# Check RabbitMQ is accessible
kubectl exec -it <pod-name> -c daprd -- \
  nc -zv rabbitmq 5672

# Check secret
kubectl get secret rabbitmq-secret -o yaml

# Check Dapr component logs
kubectl logs <pod-name> -c daprd | grep rabbitmq
```

## Uninstalling

```bash
# Uninstall Helm release
helm uninstall my-agent

# Clean up secrets
kubectl delete secret ai-model-secret rabbitmq-secret

# Verify cleanup
kubectl get pods -l app.kubernetes.io/name=agent-blueprint
```

## Advantages of Standalone Mode

✅ No cluster-admin required
✅ No Dapr control plane overhead
✅ Full control over sidecar configuration
✅ Works in restricted environments
✅ Easier debugging
✅ Portable across clusters

## Limitations

❌ Manual sidecar management
❌ No automatic injection
❌ More YAML configuration
❌ Limited Dapr features (no actors, limited mTLS)
❌ Manual version updates

## Next Steps

- [Configuration Guide](configuration.md)
- [Troubleshooting Guide](troubleshooting.md)
- [Migration to Operator Mode](deployment-approaches.md#migration-between-approaches)
