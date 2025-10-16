# Health Checks

This document describes the health check system for the agent microservice.

## Overview

The agent provides comprehensive health checks through Spring Boot-style actuator endpoints. Health checks are **optional** and can be enabled/disabled per component through configuration.

## Endpoints

### Liveness Probe
- **URL**: `GET /health/live`
- **Purpose**: Indicates if the service is running
- **Use**: Kubernetes liveness probe
- **Response**: `{"status": "UP"}` or HTTP 503 if configuration errors exist

### Readiness Probe
- **URL**: `GET /health/ready`
- **Purpose**: Indicates if the service is ready to accept traffic
- **Use**: Kubernetes readiness probe
- **Response**: Includes status of all configured components

Example response:
```json
{
  "status": "UP",
  "components": {
    "ai_provider": {
      "status": "healthy",
      "message": "vLLM reachable at https://avs-vllm.q14.net/v1"
    },
    "rabbitmq": {
      "status": "healthy",
      "message": "RabbitMQ reachable via Dapr pubsub 'rabbitmq-pubsub'"
    }
  }
}
```

## Health Check Components

### 1. AI Provider Health Check

Verifies connectivity to the configured AI model provider (vLLM or OpenAI).

**Configuration**:
```toml
# Enable/disable AI provider health check
health_check_ai_provider = true  # default: true

# AI provider configuration
ai_model_provider = "vllm"
ai_model_base_url = "https://avs-vllm.q14.net/v1"
ai_model_api_key = "your-api-key"
```

**Behavior**:
- **Disabled**: Returns `healthy` with message "AI provider health check disabled"
- **Not configured**: Returns `healthy` with message "No AI provider configured"
- **vLLM**: Checks `/health` endpoint of the vLLM server
- **OpenAI**: Always returns `healthy` (no external dependency to check)

**Health Check Logic**:
1. Verifies base URL is configured
2. Verifies API key is configured
3. Makes HTTP GET request to `{base_url}/health`
4. Returns `healthy` if response is 200 OK

### 2. RabbitMQ Health Check (via Dapr)

Verifies RabbitMQ connectivity through the Dapr pubsub component.

**Configuration**:
```toml
# Enable/disable RabbitMQ health check
health_check_rabbitmq = true  # default: true

# Dapr configuration
dapr_pubsub_name = "rabbitmq-pubsub"
dapr_http_port = 3500

# RabbitMQ configuration
rabbitmq_host = "rabbitmq.namespace.svc:5672"
rabbitmq_vhost = "bios"
```

**Behavior**:
- **Disabled**: Returns `healthy` with message "RabbitMQ health check disabled"
- **Not configured**: Returns `healthy` with message "RabbitMQ not configured"
- **Enabled**: Performs three-step verification through Dapr

**Health Check Logic**:
1. **Dapr Sidecar Check**: Verifies Dapr sidecar is reachable at `http://localhost:3500/v1.0/healthz`
2. **Component Check**: Queries Dapr metadata to verify pubsub component is loaded
3. **Publish Test**: Publishes a lightweight health check message to topic `health.check`

**Why Through Dapr?**
- Leverages existing Dapr infrastructure
- No direct RabbitMQ client dependency needed
- Tests the actual message path used by the application
- Validates both Dapr and RabbitMQ connectivity in one check

## Configuration

### Global Settings

```toml
[default]
# Health check toggles
health_check_ai_provider = true
health_check_rabbitmq = true
```

### Helm Values

```yaml
appSettings:
  # Health checks
  health_check_ai_provider: true
  health_check_rabbitmq: true
```

### Environment Variables

Health checks can also be controlled via environment variables (Dynaconf convention):

```bash
export DYNACONF_HEALTH_CHECK_AI_PROVIDER=false
export DYNACONF_HEALTH_CHECK_RABBITMQ=false
```

## Kubernetes Integration

### Liveness Probe Configuration

```yaml
livenessProbe:
  httpGet:
    path: /health/live
    port: http
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3
```

### Readiness Probe Configuration

```yaml
readinessProbe:
  httpGet:
    path: /health/ready
    port: http
  initialDelaySeconds: 10
  periodSeconds: 5
  timeoutSeconds: 3
  failureThreshold: 3
```

## Best Practices

### When to Enable Health Checks

✅ **Enable when**:
- Running in production environments
- Using Kubernetes with automatic pod restarts
- Need to verify external dependencies before accepting traffic
- Troubleshooting connectivity issues

❌ **Disable when**:
- Running in development without external dependencies
- Health check adds unwanted latency to readiness
- External service is optional and failures should not block traffic

### Recommended Configuration

**Production**:
```toml
health_check_ai_provider = true
health_check_rabbitmq = true
```

**Development (with external services)**:
```toml
health_check_ai_provider = true
health_check_rabbitmq = true
```

**Development (local only)**:
```toml
health_check_ai_provider = false
health_check_rabbitmq = false
```

## Troubleshooting

### Pod Not Ready

If pods are stuck in "Not Ready" state:

1. Check readiness probe logs:
   ```bash
   kubectl logs <pod-name> -c agent-blueprint
   ```

2. Manually test health endpoint:
   ```bash
   kubectl port-forward <pod-name> 8000:8000
   curl http://localhost:8000/health/ready
   ```

3. Check component status in response to identify failing component

### AI Provider Health Check Failing

**Symptoms**: `ai_provider` component shows `unhealthy`

**Common causes**:
- vLLM server is down or unreachable
- Incorrect `ai_model_base_url` configuration
- Invalid or missing API key
- Network connectivity issues

**Resolution**:
1. Verify vLLM server is running
2. Test connectivity: `curl https://your-vllm-server/health`
3. Verify configuration in ConfigMap/settings
4. Temporarily disable: `health_check_ai_provider = false`

### RabbitMQ Health Check Failing

**Symptoms**: `rabbitmq` component shows `unhealthy`

**Common causes**:
- Dapr sidecar not running or misconfigured
- RabbitMQ pubsub component not loaded
- RabbitMQ server is down or unreachable
- Incorrect connection string or credentials
- Network policies blocking traffic

**Resolution**:
1. Check Dapr sidecar: `curl http://localhost:3500/v1.0/healthz`
2. Check Dapr metadata: `curl http://localhost:3500/v1.0/metadata`
3. Verify pubsub component in Dapr metadata response
4. Check RabbitMQ server connectivity
5. Verify connection string in Dapr component configuration
6. Temporarily disable: `health_check_rabbitmq = false`

## Testing

### Unit Tests

Run health check unit tests:
```bash
pytest base/tests/unit/test_health_check_service.py -v
```

### Integration Tests

Test health checks against running services:
```bash
# Start services
docker-compose up -d

# Test liveness
curl http://localhost:8000/health/live

# Test readiness
curl http://localhost:8000/health/ready | jq .
```

### Manual Testing with Port-Forward

```bash
# Forward pod ports
kubectl port-forward <pod-name> 8000:8000 3500:3500

# Test liveness
curl http://localhost:8000/health/live

# Test readiness
curl http://localhost:8000/health/ready | jq .

# Check Dapr health
curl http://localhost:3500/v1.0/healthz

# Check Dapr metadata
curl http://localhost:3500/v1.0/metadata | jq .
```

## Architecture

### Class Diagram

```
┌─────────────────────────────┐
│  ActuatorApi                │
│  - config: Config           │
│  - dependencies: Dict       │
├─────────────────────────────┤
│  + readiness_probe()        │
│  + liveness_probe()         │
└─────────────┬───────────────┘
              │ uses
              ▼
┌─────────────────────────────┐
│  HealthCheckProvider        │
│  (Protocol)                 │
├─────────────────────────────┤
│  + health_check()           │
└─────────────┬───────────────┘
              │ implements
      ┌───────┴────────┐
      ▼                ▼
┌──────────────┐  ┌──────────────────────┐
│ AIProvider   │  │ DaprPubSub           │
│ HealthChecker│  │ HealthChecker        │
├──────────────┤  ├──────────────────────┤
│ - config     │  │ - config             │
│ - enabled    │  │ - enabled            │
├──────────────┤  │ - pubsub_name        │
│ + health_    │  │ - dapr_http_port     │
│   check()    │  ├──────────────────────┤
└──────────────┘  │ + health_check()     │
                  └──────────────────────┘
```

### Sequence Diagram

```
Client          ActuatorApi    AIHealthChecker    DaprHealthChecker    Dapr    RabbitMQ
  │                  │                │                    │              │         │
  ├─GET /health/ready─>              │                    │              │         │
  │                  │                │                    │              │         │
  │                  ├─health_check()─>                   │              │         │
  │                  │                ├─GET /health───────────────────────>        │
  │                  │                │<──200 OK──────────────────────────┤        │
  │                  │<───healthy─────┤                   │              │         │
  │                  │                │                    │              │         │
  │                  ├─health_check()─────────────────────>              │         │
  │                  │                │                    ├─GET /healthz─>        │
  │                  │                │                    │<─200 OK──────┤        │
  │                  │                │                    ├─GET /metadata>        │
  │                  │                │                    │<─components──┤        │
  │                  │                │                    ├─POST /publish>────────>
  │                  │                │                    │<─200 OK──────┤<───ack─┤
  │                  │<───healthy─────────────────────────┤              │         │
  │                  │                │                    │              │         │
  │<─200 {status:UP}─┤                │                    │              │         │
  │                  │                │                    │              │         │
```

## See Also

- [Configuration Management](./CONFIGURATION.md)
- [Dapr Integration](./DAPR.md)
- [Kubernetes Deployment](./deployment/README.md)
