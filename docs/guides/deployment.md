# Deployment Guide

This guide covers packaging, deploying, and operating Blueprint Agents applications in production environments using Docker, Kubernetes, and Helm.

> **Running more than one replica is not safe in the current release.** Message distribution is
> now correct on both NATS paths -- Core NATS subscriptions join a queue group (`nats_queue_group`,
> default `app_name`), JetStream consumers are durable and share a deliver group, and every
> delivery is acknowledged, redelivered or dead-lettered explicitly. Two problems remain:
>
> - **Every replica runs its own scheduler.** `SchedulerBase` starts an `AsyncIOScheduler` per
>   process with no leader election, so each cron tick fires once per replica.
> - **Duplicate delivery is not handled.** Competing consumers make at-least-once permanent, and a
>   handler that finishes its work and then fails to acknowledge -- a connection blip, a pod killed
>   mid-handler -- has already committed its side effects when the message is redelivered. The
>   framework offers no deduplication yet, so a handler that is not naturally idempotent will repeat
>   itself.
>
> The delivery behaviour above is covered by unit tests against mocked transports, and has not yet
> been exercised against a real broker.
>
> Until these are addressed, deploy one replica with `autoscaling.enabled: false`. The HPA example
> below shows the chart's shape; it is not a recommendation. Required behaviour is specified in
> `docs/specs/2026-08-28-multi-agent-grouping.md`, sec. 7.4 and 7.5; the remaining fixes are P4 and
> P5 in `docs/plans/2026-08-28-multi-agent-grouping.md`. This guide also assumes one Deployment
> per agent, and will be rewritten when group-based deployment lands.

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

#### Choosing Your Own Prefix

`DYNACONF_` is the default, not the only option. Declare `envvar_prefix` as a **top-level** key --
above every section, because the prefix is resolved before any environment section is selected:

```toml
envvar_prefix = "ORDERS"

[default]
app_name = "orders"
```

```bash
docker run -e ORDERS_MODEL_NAME="gpt-4" my-ai-service:latest
```

An operator can override the declared prefix without rebuilding the image, using the framework's
own bootstrap variable:

```bash
docker run -e BLUEPRINT_ENVVAR_PREFIX="ORDERS" -e ORDERS_MODEL_NAME="gpt-4" my-ai-service:latest
```

Three rules the service enforces at startup, each failing loudly rather than being ignored:

| Declaration | Result |
|---|---|
| `envvar_prefix = "orders"` | **Rejected.** Dynaconf upper-cases the prefix before matching, so the `orders_*` you export would never be read. Declare it in the case you will export it in. |
| `envvar_prefix = "BLUEPRINT"` or `"POD"` | **Rejected.** Stripping the prefix would turn `BLUEPRINT_GROUP` into the key `group` and expose deployment identity to agent code. |
| `envvar_prefix` inside `[default]` | **Rejected.** The prefix decides how the environment section is chosen, so it cannot live inside one. |

`DYNACONF_*` keeps working whatever prefix you declare -- Dynaconf always loads it and cannot be
told not to -- so an existing deployment can migrate one variable at a time. Where both spellings
set the same key, the declared prefix wins.

#### Turning the Prefix Off

`envvar_prefix = false` (or `BLUEPRINT_ENVVAR_PREFIX=false`) makes every environment variable a
setting, with no prefix at all:

```bash
docker run -e BLUEPRINT_ENVVAR_PREFIX=false -e MODEL_NAME="gpt-4" my-ai-service:latest
```

**This absorbs the whole process environment into your configuration** -- `PATH`, `HOSTNAME`, the
service-discovery variables Kubernetes injects for every Service in the namespace, and any
credential that happens to be exported. Measured on a development machine: 88 settings keys from a
5-key settings file. Anything colliding with one of your key names silently replaces it.

Prefer a short project prefix. Use `false` only for a container whose environment you fully control
and deliberately want to pass through -- and read the startup log line, which states which prefix
the process resolved.

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
replicaCount: 1  # multi-replica is unsafe in this release; see the warning at the top

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
    --set replicaCount=1        # see the warning at the top: more than one is unsafe in this release

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

> **Event broker startup**: the broker connection (NATS / Dapr) is established asynchronously after startup. `/health/ready` returns `503` until the broker is reachable and all topic subscriptions are active. Set `failureThreshold` high enough to tolerate the broker's own startup time — see [Broker Startup Resilience](../concepts/event-processing.md#broker-startup-resilience).

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

Leave autoscaling disabled in the current release — see the warning at the top of this guide.
Scaling past one replica multiplies event processing, acknowledgement loss and cron ticks
rather than throughput.

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
