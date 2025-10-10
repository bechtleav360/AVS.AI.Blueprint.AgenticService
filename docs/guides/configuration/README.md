# Configuration Guide

**Complete configuration reference for Agent Blueprint**

This directory contains in-depth guides for configuring your agent and Dapr components.

## 📚 Configuration Guides

### [Agent Configuration](agent-configuration.md)
Quick reference for agent-specific settings:
- AI model configuration (OpenAI, vLLM, Anthropic)
- Application settings
- Data Gateway configuration
- Environment-specific settings
- Custom configuration

### [Dynaconf](dynaconf.md)
Configuration management system:
- Settings files (`settings.toml`, `secrets.toml`)
- Environment variables
- Configuration priority
- Nested configuration
- Validation
- Best practices

### [OpenTelemetry](opentelemetry.md)
Distributed tracing and observability:
- Tracing configuration
- Sampling strategies
- Backend integration (Jaeger, Zipkin, Datadog, etc.)
- Custom instrumentation
- Performance tuning
- Troubleshooting

### [Dapr Configuration](dapr-configuration.md)
Event processing and pub/sub:
- Pub/Sub components (RabbitMQ, Kafka, Azure Service Bus)
- Event subscriptions
- Secrets management
- Production settings
- High availability setup
- Monitoring and debugging

## Quick Start

### 1. Basic Agent Configuration

```toml
# custom/settings.toml
[default]
app_name = "my-agent"
ai_model_provider = "openai"
ai_model_name = "gpt-4"
```

```toml
# custom/secrets.toml
[default]
ai_model_api_key = "sk-your-key"
```

### 2. Basic Dapr Configuration

```yaml
# custom/dapr/components/rabbitmq-pubsub.yaml
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
      value: "guest"
    - name: password
      value: "guest"
```

```yaml
# custom/dapr/subscriptions/events.yaml
apiVersion: dapr.io/v2alpha1
kind: Subscription
metadata:
  name: events-subscription
spec:
  pubsubname: rabbitmq-pubsub
  topic: my.events
  routes:
    default: /events/process
```

## Configuration Hierarchy

```
1. settings.toml [default]
   ↓
2. settings.toml [environment]
   ↓
3. secrets.toml
   ↓
4. Environment variables (highest priority)
```

## Common Configuration Tasks

### Configure AI Model

See [Agent Configuration - AI Model Configuration](agent-configuration.md#ai-model-configuration)

### Configure RabbitMQ

See [Dapr Configuration - RabbitMQ Component](dapr-configuration.md#rabbitmq-component)

### Configure Event Subscriptions

See [Dapr Configuration - Event Subscriptions](dapr-configuration.md#event-subscriptions)

### Configure for Production

See:
- [Agent Configuration - Production Configuration](agent-configuration.md#production-configuration)
- [Dapr Configuration - Production Configuration](dapr-configuration.md#production-configuration)

## Configuration Examples

### Development Setup

```toml
# settings.toml
[development]
log_level = "DEBUG"
ai_model_timeout = 120
otel_enabled = false
```

```bash
export ENVIRONMENT=development
cd custom && ./start_with_dapr.sh
```

### Production Setup

```toml
# settings.toml
[production]
log_level = "WARNING"
ai_model_timeout = 60
otel_enabled = true
otel_endpoint = "https://otel-collector.prod.example.com"
```

```bash
export ENVIRONMENT=production
export AI_MODEL_API_KEY="sk-prod-key"
kubectl apply -f k8s/
```

## Troubleshooting

### Configuration Not Loading

1. Check file exists: `ls -la custom/settings.toml`
2. Validate TOML: `python -c "import tomli; tomli.load(open('custom/settings.toml', 'rb'))"`
3. Check working directory

### Dapr Component Not Loading

1. Check YAML syntax: `yamllint custom/dapr/components/*.yaml`
2. Check Dapr logs: `dapr logs --app-id agent_blueprint`
3. Verify component path: `--resources-path ./dapr/components`

### Connection Issues

1. Test RabbitMQ: `curl -u guest:guest http://localhost:15672/api/overview`
2. Check port forwarding: `lsof -i :5672`
3. Verify credentials in component file

## See Also

- [Getting Started Guide](../getting-started.md) - Initial setup
- [Events Setup Guide](../events-setup.md) - Step-by-step event configuration
- [Deployment Guide](../deployment.md) - Production deployment
- [Troubleshooting](../troubleshooting.md) - Common issues

---

**Need help?** Check the specific guides above or see [Troubleshooting](../troubleshooting.md).
