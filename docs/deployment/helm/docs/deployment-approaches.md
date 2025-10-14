# Deployment Approaches

The Agent Blueprint can be deployed with Dapr in two different ways, each with its own advantages and use cases.

## Overview

| Approach | Dapr Operator | Complexity | Best For |
|----------|--------------|------------|----------|
| **With Dapr Operator** | Required | Lower | Production, Kubernetes clusters |
| **Without Dapr Operator** | Not required | Higher | Edge, restricted environments, standalone |

## Approach 1: With Dapr Operator (Recommended)

This is the **recommended approach** for most Kubernetes deployments. The Dapr operator manages the sidecar injection and component lifecycle automatically.

### Architecture

```
┌─────────────────────────────────────────┐
│           Kubernetes Cluster             │
│                                          │
│  ┌────────────────────────────────────┐ │
│  │      Dapr Control Plane            │ │
│  │  ┌──────────┐  ┌──────────────┐   │ │
│  │  │ Operator │  │   Sidecar    │   │ │
│  │  │          │  │   Injector   │   │ │
│  │  └──────────┘  └──────────────┘   │ │
│  │  ┌──────────┐  ┌──────────────┐   │ │
│  │  │Placement │  │   Sentinel   │   │ │
│  │  └──────────┘  └──────────────┘   │ │
│  └────────────────────────────────────┘ │
│                                          │
│  ┌────────────────────────────────────┐ │
│  │         Your Application           │ │
│  │  ┌──────────────┐  ┌───────────┐  │ │
│  │  │     App      │  │   Dapr    │  │ │
│  │  │  Container   │  │  Sidecar  │  │ │
│  │  │              │  │ (injected)│  │ │
│  │  └──────────────┘  └───────────┘  │ │
│  └────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

### How It Works

1. **Dapr Operator** watches for pods with Dapr annotations
2. **Sidecar Injector** automatically injects the Dapr sidecar container
3. **Components** are managed as Kubernetes CRDs
4. **Subscriptions** are managed as Kubernetes CRDs

### Prerequisites

- Kubernetes 1.19+
- Helm 3.2.0+
- Dapr 1.10+ installed on cluster

### Installation

#### Step 1: Install Dapr on Kubernetes

```bash
# Install Dapr CLI
wget -q https://raw.githubusercontent.com/dapr/cli/master/install/install.sh -O - | /bin/bash

# Initialize Dapr on Kubernetes
dapr init -k

# Verify Dapr installation
dapr status -k

# Expected output:
# NAME                   NAMESPACE    HEALTHY  STATUS   REPLICAS  VERSION  AGE  CREATED
# dapr-sentry            dapr-system  True     Running  1         1.12.0   1m   2024-01-15 10:00.00
# dapr-operator          dapr-system  True     Running  1         1.12.0   1m   2024-01-15 10:00.00
# dapr-sidecar-injector  dapr-system  True     Running  1         1.12.0   1m   2024-01-15 10:00.00
# dapr-placement-server  dapr-system  True     Running  1         1.12.0   1m   2024-01-15 10:00.00
```

#### Step 2: Create Secrets

```bash
# AI Model API key
kubectl create secret generic ai-model-secret \
  --from-literal=openai_api_key='sk-proj-your-key-here'

# RabbitMQ credentials (if using external RabbitMQ)
kubectl create secret generic rabbitmq-secret \
  --from-literal=host='amqp://user:pass@rabbitmq:5672'
```

#### Step 3: Deploy with Helm

```bash
# Install the chart
helm install my-agent ./agent-blueprint

# The Dapr operator will automatically:
# - Inject the Dapr sidecar
# - Configure the sidecar based on annotations
# - Register components and subscriptions
```

#### Step 4: Verify Deployment

```bash
# Check pods (should see 2 containers: app + daprd)
kubectl get pods -l app.kubernetes.io/name=agent-blueprint

# Expected output:
# NAME                                READY   STATUS    RESTARTS   AGE
# my-agent-agent-blueprint-xxx-xxx    2/2     Running   0          1m

# Check Dapr components
kubectl get components

# Check subscriptions
kubectl get subscriptions
```

### Configuration

The Helm chart uses Dapr annotations for automatic sidecar injection:

```yaml
# In deployment.yaml template
annotations:
  dapr.io/enabled: "true"
  dapr.io/app-id: "agent-blueprint"
  dapr.io/app-port: "8000"
  dapr.io/http-port: "3500"
  dapr.io/grpc-port: "50001"
  dapr.io/log-level: "info"
```

### Advantages

✅ **Automatic sidecar injection** - No manual container configuration
✅ **Centralized management** - Dapr control plane manages all sidecars
✅ **Easy updates** - Update Dapr version cluster-wide
✅ **Component CRDs** - Kubernetes-native component management
✅ **Service mesh integration** - Works with Istio, Linkerd, etc.
✅ **Production-ready** - Battle-tested in production environments
✅ **Monitoring** - Built-in metrics and tracing

### Disadvantages

❌ **Requires cluster-admin** - Need permissions to install Dapr
❌ **Additional resources** - Dapr control plane consumes resources
❌ **Cluster dependency** - Tied to Kubernetes cluster
❌ **Learning curve** - Need to understand Dapr concepts

### Use Cases

- **Production deployments** on Kubernetes
- **Multi-tenant environments** with many Dapr apps
- **Microservices architectures** with service-to-service calls
- **Teams familiar with Kubernetes** and CRDs
- **Environments with cluster-admin access**

---

## Approach 2: Without Dapr Operator (Standalone)

This approach runs Dapr as a regular sidecar container without the operator. Useful for restricted environments or edge deployments.

### Architecture

```
┌─────────────────────────────────────────┐
│           Kubernetes Cluster             │
│         (No Dapr Control Plane)          │
│                                          │
│  ┌────────────────────────────────────┐ │
│  │         Your Application           │ │
│  │  ┌──────────────┐  ┌───────────┐  │ │
│  │  │     App      │  │   Dapr    │  │ │
│  │  │  Container   │  │  Sidecar  │  │ │
│  │  │              │  │ (manual)  │  │ │
│  │  └──────────────┘  └───────────┘  │ │
│  │                                    │ │
│  │  ConfigMaps for Dapr components   │ │
│  └────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

### How It Works

1. **Manual sidecar** container defined in deployment
2. **Components** configured via ConfigMaps mounted as files
3. **Subscriptions** configured via ConfigMaps or programmatic API
4. **No operator** - Everything is standard Kubernetes resources

### Prerequisites

- Kubernetes 1.19+
- Helm 3.2.0+
- **No Dapr installation required**

### Installation

#### Step 1: Create Secrets

```bash
# AI Model API key
kubectl create secret generic ai-model-secret \
  --from-literal=openai_api_key='sk-proj-your-key-here'

# RabbitMQ credentials
kubectl create secret generic rabbitmq-secret \
  --from-literal=host='amqp://user:pass@rabbitmq:5672'
```

#### Step 2: Deploy with Helm (Standalone Mode)

```bash
# Create values file for standalone mode
cat > standalone-values.yaml <<EOF
# Disable Dapr operator mode
dapr:
  enabled: false
  standalone: true

# Manually configure sidecar
daprSidecar:
  enabled: true
  image: daprio/daprd:1.12.0
  appId: agent-blueprint
  appPort: 8000
  httpPort: 3500
  grpcPort: 50001
  metricsPort: 9090
  logLevel: info
  
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: 1000m
      memory: 512Mi

# Components as ConfigMaps
daprComponents:
  asConfigMaps: true
  rabbitmq:
    enabled: true
    host: "amqp://rabbitmq:5672"
    vhost: "bios"

# Subscriptions via programmatic API
subscriptions:
  mode: programmatic  # or configmap
EOF

# Install with standalone configuration
helm install my-agent ./agent-blueprint -f standalone-values.yaml
```

#### Step 3: Verify Deployment

```bash
# Check pods (should see 2 containers: app + daprd)
kubectl get pods -l app.kubernetes.io/name=agent-blueprint

# Check that Dapr sidecar is running
kubectl describe pod <pod-name>

# Test Dapr sidecar
kubectl exec -it <pod-name> -c daprd -- /daprd --version
```

### Configuration

For standalone mode, you need to manually define the Dapr sidecar container:

```yaml
# Additional container in deployment
containers:
- name: daprd
  image: daprio/daprd:1.12.0
  command:
    - "/daprd"
  args:
    - "--app-id"
    - "agent-blueprint"
    - "--app-port"
    - "8000"
    - "--dapr-http-port"
    - "3500"
    - "--dapr-grpc-port"
    - "50001"
    - "--metrics-port"
    - "9090"
    - "--log-level"
    - "info"
    - "--components-path"
    - "/components"
  ports:
    - containerPort: 3500
      name: dapr-http
    - containerPort: 50001
      name: dapr-grpc
    - containerPort: 9090
      name: metrics
  volumeMounts:
    - name: dapr-components
      mountPath: /components
      readOnly: true
```

Components are defined as regular YAML files in ConfigMaps:

```yaml
# ConfigMap for Dapr components
apiVersion: v1
kind: ConfigMap
metadata:
  name: dapr-components
data:
  pubsub.yaml: |
    apiVersion: dapr.io/v1alpha1
    kind: Component
    metadata:
      name: rabbitmq-pubsub
    spec:
      type: pubsub.rabbitmq
      version: v1
      metadata:
        - name: host
          value: "amqp://rabbitmq:5672"
```

### Advantages

✅ **No cluster dependencies** - Works without Dapr operator
✅ **Full control** - Complete control over sidecar configuration
✅ **Restricted environments** - Works in air-gapped or restricted clusters
✅ **Edge deployments** - Suitable for edge/IoT scenarios
✅ **Simpler permissions** - No cluster-admin required
✅ **Portable** - Can run anywhere Kubernetes runs
✅ **Debugging** - Easier to debug sidecar issues

### Disadvantages

❌ **Manual management** - Must manually update sidecar versions
❌ **More configuration** - More YAML to write and maintain
❌ **No automatic injection** - Must define sidecar in every deployment
❌ **Limited features** - Some Dapr features require operator
❌ **Scaling complexity** - Harder to manage at scale
❌ **No service mesh** - Limited integration with service meshes

### Use Cases

- **Edge deployments** with limited connectivity
- **Air-gapped environments** without internet access
- **Restricted clusters** without cluster-admin permissions
- **Development/testing** without full Dapr installation
- **Single application** deployments
- **IoT scenarios** with resource constraints
- **Compliance requirements** needing full control

---

## Comparison

### Feature Comparison

| Feature | With Operator | Without Operator |
|---------|--------------|------------------|
| Automatic sidecar injection | ✅ Yes | ❌ No (manual) |
| Component CRDs | ✅ Yes | ❌ No (ConfigMaps) |
| Subscription CRDs | ✅ Yes | ❌ No (ConfigMaps/API) |
| Service invocation | ✅ Yes | ✅ Yes |
| Pub/Sub | ✅ Yes | ✅ Yes |
| State management | ✅ Yes | ✅ Yes |
| Secrets | ✅ Yes | ✅ Yes |
| Bindings | ✅ Yes | ✅ Yes |
| Actors | ✅ Yes | ⚠️ Limited |
| Distributed tracing | ✅ Yes | ✅ Yes |
| Metrics | ✅ Yes | ✅ Yes |
| mTLS | ✅ Yes | ⚠️ Manual setup |
| Service mesh integration | ✅ Yes | ❌ No |
| Multi-app management | ✅ Easy | ❌ Complex |
| Version updates | ✅ Centralized | ❌ Per-deployment |

### Resource Usage

| Resource | With Operator | Without Operator |
|----------|--------------|------------------|
| Control plane | ~500MB | 0MB |
| Per-app sidecar | ~50-100MB | ~50-100MB |
| CPU overhead | Low | Low |
| Network overhead | Low | Low |

### Operational Complexity

| Task | With Operator | Without Operator |
|------|--------------|------------------|
| Initial setup | Medium | Low |
| Day-to-day ops | Low | Medium |
| Updates | Easy | Manual |
| Troubleshooting | Medium | Hard |
| Scaling | Easy | Medium |

---

## Decision Guide

### Choose **With Dapr Operator** if:

- ✅ You have cluster-admin permissions
- ✅ Running in a standard Kubernetes cluster
- ✅ Managing multiple Dapr applications
- ✅ Need automatic sidecar injection
- ✅ Want centralized management
- ✅ Production environment
- ✅ Team familiar with Kubernetes operators

### Choose **Without Dapr Operator** if:

- ✅ No cluster-admin permissions
- ✅ Restricted or air-gapped environment
- ✅ Edge or IoT deployment
- ✅ Single application deployment
- ✅ Need full control over configuration
- ✅ Compliance requirements
- ✅ Development/testing without full setup

---

## Migration Between Approaches

### From Operator to Standalone

```bash
# 1. Export current configuration
kubectl get component rabbitmq-pubsub -o yaml > component.yaml
kubectl get subscription my-sub -o yaml > subscription.yaml

# 2. Convert to ConfigMap format
# (Manual conversion needed)

# 3. Uninstall operator-based deployment
helm uninstall my-agent

# 4. Install standalone version
helm install my-agent ./agent-blueprint -f standalone-values.yaml
```

### From Standalone to Operator

```bash
# 1. Install Dapr on cluster
dapr init -k

# 2. Convert ConfigMaps to CRDs
# (Manual conversion needed)

# 3. Uninstall standalone deployment
helm uninstall my-agent

# 4. Install operator-based version
helm install my-agent ./agent-blueprint
```

---

## Next Steps

- **With Operator**: See [Installation with Operator](installation-with-operator.md)
- **Without Operator**: See [Installation without Operator](installation-without-operator.md)
- **Configuration**: See [Configuration Guide](configuration.md)
- **Troubleshooting**: See [Troubleshooting Guide](troubleshooting.md)
