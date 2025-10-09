# Dapr Components

This directory contains Dapr component configurations for the agent service.

## RabbitMQ PubSub Component

The RabbitMQ pubsub component is generated from a template at runtime to inject credentials from Dynaconf settings.

### Files:
- **`rabbitmq-pubsub.yaml.template`** - Template file with `$RABBITMQ_CONNECTION` placeholder (committed to git)
- **`rabbitmq-pubsub.yaml`** - Generated file with actual credentials (gitignored, auto-generated)

### Configuration Source:
- **Host**: `custom/settings.toml` → `rabbitmq_host`
- **Credentials**: `custom/secrets.toml` → `rabbitmq_username`, `rabbitmq_password`

### Generation Process:
1. `export_rabbitmq_env.sh` loads settings from Dynaconf
2. Exports `RABBITMQ_CONNECTION` environment variable
3. `envsubst` substitutes `$RABBITMQ_CONNECTION` in template
4. Generates `rabbitmq-pubsub.yaml` for Dapr to consume

### Usage:
The component is automatically generated when running:
- `./start_with_dapr.sh`
- VS Code launch configuration "Dapr: sidecar"

### Manual Generation:
```bash
cd custom
source export_rabbitmq_env.sh
envsubst < dapr/components/rabbitmq-pubsub.yaml.template > dapr/components/rabbitmq-pubsub.yaml
```

---

## Kubernetes Deployment

For production Kubernetes deployments, Dapr components should be managed separately from the application repository using Helm charts or Kubernetes manifests.

### Recommended Approach: Helm Chart

**Location**: Separate Helm chart repository

**Structure**:
```
helm-charts/agent-service/
├── Chart.yaml
├── values.yaml
├── values-dev.yaml
├── values-staging.yaml
├── values-prod.yaml
└── templates/
    ├── deployment.yaml
    ├── service.yaml
    ├── dapr-config.yaml
    └── components/
        ├── rabbitmq-pubsub.yaml
        └── statestore.yaml (if needed)
```

### Configuration Steps

#### 1. Create Dapr Component Template

**File**: `templates/components/rabbitmq-pubsub.yaml`

```yaml
apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: rabbitmq-pubsub
  namespace: {{ .Values.namespace }}
spec:
  type: pubsub.rabbitmq
  version: v1
  metadata:
  - name: host
    value: {{ .Values.rabbitmq.host }}
  - name: consumerID
    value: {{ .Values.app.name }}
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
    value: "5"
  - name: concurrency
    value: "parallel"
{{- if .Values.rabbitmq.useSecret }}
  - name: username
    secretKeyRef:
      name: {{ .Values.rabbitmq.secretName }}
      key: username
  - name: password
    secretKeyRef:
      name: {{ .Values.rabbitmq.secretName }}
      key: password
{{- else }}
  - name: username
    value: {{ .Values.rabbitmq.username }}
  - name: password
    value: {{ .Values.rabbitmq.password }}
{{- end }}
```

#### 2. Create Dapr Configuration Template

**File**: `templates/dapr-config.yaml`

```yaml
apiVersion: dapr.io/v1alpha1
kind: Configuration
metadata:
  name: dapr-config
  namespace: {{ .Values.namespace }}
spec:
  tracing:
    samplingRate: "{{ .Values.dapr.tracing.samplingRate }}"
    otel:
      endpointAddress: "{{ .Values.dapr.tracing.endpoint }}"
  logging:
    appLogDestination: "console"
    appLogLevel: "{{ .Values.dapr.logging.level }}"
  metric:
    enabled: {{ .Values.dapr.metrics.enabled }}
  accessControl:
    defaultAction: "allow"
    trustDomain: "{{ .Values.dapr.trustDomain }}"
```

#### 3. Configure Values Files

**File**: `values-prod.yaml`

```yaml
namespace: production

app:
  name: agent-service
  replicas: 3

rabbitmq:
  host: "amqp://rabbitmq.production.svc.cluster.local:5672"
  useSecret: true
  secretName: rabbitmq-credentials
  # username and password not needed when using secret

dapr:
  enabled: true
  appId: agent-service
  appPort: 8000
  tracing:
    samplingRate: "0.1"
    endpoint: "http://otel-collector.observability.svc.cluster.local:4317"
  logging:
    level: "info"
  metrics:
    enabled: true
  trustDomain: "production"
```

**File**: `values-dev.yaml`

```yaml
namespace: development

app:
  name: agent-service
  replicas: 1

rabbitmq:
  host: "amqp://rabbitmq.development.svc.cluster.local:5672"
  useSecret: false
  username: "guest"
  password: "guest"

dapr:
  enabled: true
  appId: agent-service
  appPort: 8000
  tracing:
    samplingRate: "1.0"
    endpoint: "http://localhost:4317"
  logging:
    level: "debug"
  metrics:
    enabled: true
  trustDomain: "development"
```

#### 4. Create Kubernetes Secret (Production)

For production, create a Kubernetes secret with RabbitMQ credentials:

```bash
kubectl create secret generic rabbitmq-credentials \
  --from-literal=username='prod-user' \
  --from-literal=password='secure-password' \
  --namespace=production
```

Or using a YAML manifest:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: rabbitmq-credentials
  namespace: production
type: Opaque
stringData:
  username: prod-user
  password: secure-password
```

**Best Practice**: Use external secret management (Azure Key Vault, AWS Secrets Manager, HashiCorp Vault) with tools like:
- External Secrets Operator
- Sealed Secrets
- SOPS

#### 5. Update Deployment Manifest

Ensure your deployment has Dapr annotations:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Values.app.name }}
  namespace: {{ .Values.namespace }}
spec:
  replicas: {{ .Values.app.replicas }}
  template:
    metadata:
      annotations:
        dapr.io/enabled: "true"
        dapr.io/app-id: "{{ .Values.dapr.appId }}"
        dapr.io/app-port: "{{ .Values.dapr.appPort }}"
        dapr.io/config: "dapr-config"
        dapr.io/log-level: "{{ .Values.dapr.logging.level }}"
    spec:
      containers:
      - name: {{ .Values.app.name }}
        image: {{ .Values.image.repository }}:{{ .Values.image.tag }}
        # ... rest of container spec
```

### Deployment Commands

#### Install/Upgrade with Helm

```bash
# Development
helm upgrade --install agent-service ./helm-charts/agent-service \
  -f helm-charts/agent-service/values-dev.yaml \
  --namespace development \
  --create-namespace

# Staging
helm upgrade --install agent-service ./helm-charts/agent-service \
  -f helm-charts/agent-service/values-staging.yaml \
  --namespace staging \
  --create-namespace

# Production
helm upgrade --install agent-service ./helm-charts/agent-service \
  -f helm-charts/agent-service/values-prod.yaml \
  --namespace production \
  --create-namespace
```

#### Verify Deployment

```bash
# Check Dapr components
kubectl get components -n production

# Check Dapr configuration
kubectl get configuration -n production

# Check pod status
kubectl get pods -n production

# Check Dapr sidecar logs
kubectl logs -n production <pod-name> -c daprd

# Check application logs
kubectl logs -n production <pod-name> -c agent-service
```

### Environment-Specific Configuration

| Environment | RabbitMQ Host | Tracing Rate | Replicas | Secret Management |
|-------------|---------------|--------------|----------|-------------------|
| **Development** | `rabbitmq.dev.svc` | 100% | 1 | Plain values |
| **Staging** | `rabbitmq.staging.svc` | 50% | 2 | Kubernetes Secret |
| **Production** | `rabbitmq.prod.svc` | 10% | 3+ | External Secret Manager |

### Troubleshooting

**Component not loading**:
```bash
# Check component status
kubectl describe component rabbitmq-pubsub -n production

# Check Dapr operator logs
kubectl logs -n dapr-system -l app=dapr-operator
```

**Connection issues**:
```bash
# Test RabbitMQ connectivity from pod
kubectl exec -it <pod-name> -n production -- curl http://rabbitmq.production.svc:15672

# Check secret is mounted correctly
kubectl get secret rabbitmq-credentials -n production -o yaml
```

**Subscription not working**:
```bash
# Check Dapr subscriptions
kubectl get subscription -n production

# Verify topic configuration in RabbitMQ
kubectl port-forward svc/rabbitmq 15672:15672 -n production
# Open http://localhost:15672 in browser
```

### Migration from Local to Kubernetes

1. **Test locally** with `./start_with_dapr.sh`
2. **Create Helm chart** with templated components
3. **Deploy to dev** environment first
4. **Validate** subscriptions and message flow
5. **Promote** to staging/production with environment-specific values
6. **Monitor** using Dapr dashboard and application metrics

### Additional Resources

- [Dapr Kubernetes Deployment](https://docs.dapr.io/operations/hosting/kubernetes/)
- [Dapr Component Specs](https://docs.dapr.io/reference/components-reference/)
- [Helm Best Practices](https://helm.sh/docs/chart_best_practices/)
