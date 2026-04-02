# Deployment Guide

This guide covers packaging, deploying, and operating Blueprint Agents applications in production environments using Docker, Kubernetes, and Helm.

---

## Docker

### Dockerfile

Blueprint Agents projects ship with a multi-stage Dockerfile. The following template provides a production-ready build:

```dockerfile
# Stage 1: Base image
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Stage 2: Builder
FROM base AS builder

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml

COPY src/ ./src/

# Stage 3: Production
FROM base AS production

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app

COPY settings.toml ./
COPY prompts/ ./prompts/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live')"]

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Building and Running

```bash
# Build the image
docker build -t my-ai-service:latest .

# Run the container
docker run -d \
    --name my-ai-service \
    -p 8000:8000 \
    -e DYNACONF_LLM__API_KEY="sk-..." \
    my-ai-service:latest
```

### Environment Variable Overrides

Blueprint Agents uses Dynaconf for configuration. Any setting in `settings.toml` can be overridden at runtime using environment variables prefixed with `DYNACONF_`:

```bash
docker run -d \
    -p 8000:8000 \
    -e DYNACONF_APP__PORT=9000 \
    -e DYNACONF_LLM__PROVIDER="openai" \
    -e DYNACONF_LLM__MODEL="gpt-4" \
    -e DYNACONF_LLM__API_KEY="sk-..." \
    -e DYNACONF_CACHE__TTL=3600 \
    my-ai-service:latest
```

Nested settings use double underscores as separators. For example, `DYNACONF_LLM__API_KEY` maps to `settings.toml` entry:

```toml
[llm]
api_key = "sk-..."
```

---

## Kubernetes with Helm

### Helm Chart Structure

```
helm/
  Chart.yaml
  values.yaml
  templates/
    deployment.yaml
    service.yaml
    configmap.yaml
    hpa.yaml
```

### values.yaml

```yaml
replicaCount: 2

image:
  repository: myregistry.azurecr.io/my-ai-service
  tag: "latest"
  pullPolicy: IfNotPresent

service:
  type: ClusterIP
  port: 80
  targetPort: 8000

dapr:
  enabled: true
  appId: "my-ai-service"
  appPort: 8000
  logLevel: "info"

app:
  port: 8000
  logLevel: "info"

resources:
  requests:
    cpu: 250m
    memory: 512Mi
  limits:
    cpu: "1"
    memory: 1Gi

probes:
  liveness:
    path: /health/live
    initialDelaySeconds: 15
    periodSeconds: 20
    timeoutSeconds: 5
    failureThreshold: 3
  readiness:
    path: /health/ready
    initialDelaySeconds: 10
    periodSeconds: 10
    timeoutSeconds: 5
    failureThreshold: 3

autoscaling:
  enabled: false
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
```

### Deployment Template

```yaml
# templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}
  labels:
    app: {{ .Release.Name }}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      app: {{ .Release.Name }}
  template:
    metadata:
      labels:
        app: {{ .Release.Name }}
      annotations:
        {{- if .Values.dapr.enabled }}
        dapr.io/enabled: "true"
        dapr.io/app-id: {{ .Values.dapr.appId | quote }}
        dapr.io/app-port: {{ .Values.dapr.appPort | quote }}
        dapr.io/log-level: {{ .Values.dapr.logLevel | quote }}
        {{- end }}
    spec:
      containers:
        - name: {{ .Release.Name }}
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          ports:
            - containerPort: {{ .Values.app.port }}
          envFrom:
            - configMapRef:
                name: {{ .Release.Name }}-config
            - secretRef:
                name: {{ .Release.Name }}-secrets
                optional: true
          livenessProbe:
            httpGet:
              path: {{ .Values.probes.liveness.path }}
              port: {{ .Values.app.port }}
            initialDelaySeconds: {{ .Values.probes.liveness.initialDelaySeconds }}
            periodSeconds: {{ .Values.probes.liveness.periodSeconds }}
            timeoutSeconds: {{ .Values.probes.liveness.timeoutSeconds }}
            failureThreshold: {{ .Values.probes.liveness.failureThreshold }}
          readinessProbe:
            httpGet:
              path: {{ .Values.probes.readiness.path }}
              port: {{ .Values.app.port }}
            initialDelaySeconds: {{ .Values.probes.readiness.initialDelaySeconds }}
            periodSeconds: {{ .Values.probes.readiness.periodSeconds }}
            timeoutSeconds: {{ .Values.probes.readiness.timeoutSeconds }}
            failureThreshold: {{ .Values.probes.readiness.failureThreshold }}
          resources:
            {{- toYaml .Values.resources | nindent 12 }}
```

### Service Template

```yaml
# templates/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ .Release.Name }}
spec:
  type: {{ .Values.service.type }}
  ports:
    - port: {{ .Values.service.port }}
      targetPort: {{ .Values.service.targetPort }}
      protocol: TCP
  selector:
    app: {{ .Release.Name }}
```

### ConfigMap Template

```yaml
# templates/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ .Release.Name }}-config
data:
  DYNACONF_APP__PORT: {{ .Values.app.port | quote }}
  DYNACONF_APP__LOG_LEVEL: {{ .Values.app.logLevel | quote }}
```

### Deploying with Helm

```bash
# Install the chart
helm install my-ai-service ./helm \
    --namespace ai-services \
    --create-namespace

# Install with custom values
helm install my-ai-service ./helm \
    --namespace ai-services \
    --set image.tag="v1.2.3" \
    --set replicaCount=3

# Upgrade an existing release
helm upgrade my-ai-service ./helm \
    --namespace ai-services \
    --set image.tag="v1.3.0"

# Uninstall
helm uninstall my-ai-service --namespace ai-services
```

---

## Health Probes

Blueprint Agents provides three built-in health endpoints:

### /health/live

Returns a simple liveness check indicating the application process is running.

```json
{
    "status": "alive"
}
```

Use this for the Kubernetes liveness probe. If this endpoint fails, the container should be restarted.

### /health/ready

Returns a readiness check indicating the application and its dependencies are ready to serve traffic.

```json
{
    "status": "ready"
}
```

Use this for the Kubernetes readiness probe. If this endpoint fails, the pod is removed from the service load balancer until it recovers.

### /health/detailed

Returns component-level health status for debugging and monitoring.

```json
{
    "status": "healthy",
    "components": {
        "cache": {"status": "healthy", "latency_ms": 2},
        "llm_provider": {"status": "healthy", "latency_ms": 150},
        "event_bus": {"status": "healthy", "latency_ms": 5}
    }
}
```

### Kubernetes Probe Configuration

```yaml
livenessProbe:
  httpGet:
    path: /health/live
    port: 8000
  initialDelaySeconds: 15
  periodSeconds: 20
  timeoutSeconds: 5
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /health/ready
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3
```

---

## Environment Configuration

### Settings via ConfigMap

Non-sensitive configuration values belong in a Kubernetes ConfigMap:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: my-ai-service-config
data:
  DYNACONF_APP__PORT: "8000"
  DYNACONF_APP__LOG_LEVEL: "info"
  DYNACONF_CACHE__TTL: "3600"
  DYNACONF_LLM__PROVIDER: "openai"
  DYNACONF_LLM__MODEL: "gpt-4"
```

### Secrets via Kubernetes Secrets

Sensitive values such as API keys and credentials belong in Kubernetes Secrets:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: my-ai-service-secrets
type: Opaque
stringData:
  DYNACONF_LLM__API_KEY: "sk-..."
  DYNACONF_DATABASE__PASSWORD: "secret-password"
```

### Dynaconf Override Hierarchy

Dynaconf resolves configuration in the following order (later sources override earlier ones):

1. `settings.toml` -- base configuration baked into the image
2. `secrets.toml` -- local secrets (not used in production)
3. Environment variables -- ConfigMap and Secret values injected into the pod

This means environment variables always take precedence over file-based configuration.

---

## Scaling Considerations

### Horizontal Pod Autoscaling

Enable automatic scaling based on CPU utilization:

```yaml
# templates/hpa.yaml
{{- if .Values.autoscaling.enabled }}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {{ .Release.Name }}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {{ .Release.Name }}
  minReplicas: {{ .Values.autoscaling.minReplicas }}
  maxReplicas: {{ .Values.autoscaling.maxReplicas }}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: {{ .Values.autoscaling.targetCPUUtilizationPercentage }}
{{- end }}
```

### Cache Considerations

When running multiple replicas, be aware of cache behavior:

- **File-based cache**: Uses file-based locking to prevent corruption. If replicas share a volume, locking ensures consistency. If each replica has its own volume, caches are independent and may diverge.
- **Recommendation**: For multi-replica deployments, prefer an external cache (Redis, Memcached) over file-based caching to ensure consistency across all replicas.

### Stateless Design

Handlers and services should be designed as stateless components:

- Do not store request-specific state in instance variables.
- Use the cache service for data that must persist across requests.
- Use the event bus for inter-service communication rather than in-memory shared state.
- Any initialization that must happen once should be performed in `on_startup()` and should be idempotent.
