# Configuration Reference

Complete configuration options for the Agent Blueprint.

## Configuration Files

### settings.toml

Non-sensitive configuration:

```toml
[default]
# Application
app_name = "my-agent"
app_port = 8001
log_level = "INFO"

# AI Model
ai_model_provider = "openai"  # or "vllm"
ai_model_name = "gpt-4"
ai_model_timeout = 60

# Observability
otel_enabled = true
otel_endpoint = "http://localhost:4317"

[development]
log_level = "DEBUG"

[production]
log_level = "WARNING"
```

### secrets.toml

Sensitive data (never commit to git):

```toml
[default]
ai_model_api_key = "sk-your-key"
ai_model_base_url = "https://api.openai.com/v1"
database_password = "secret"
```

## Environment Variables

Override any setting with environment variables:

```bash
export APP_NAME="my-agent"
export LOG_LEVEL="DEBUG"
export AI_MODEL_API_KEY="sk-new-key"
```

## Configuration Priority

```
1. settings.toml (lowest priority)
2. secrets.toml
3. Environment variables (highest priority)
```

## Available Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `app_name` | string | "agent" | Service name |
| `app_port` | int | 8001 | HTTP port |
| `log_level` | string | "INFO" | Log level (DEBUG, INFO, WARNING, ERROR) |
| `ai_model_provider` | string | "openai" | AI provider (openai, vllm) |
| `ai_model_name` | string | "gpt-4" | Model name |
| `ai_model_api_key` | string | - | API key (required) |
| `ai_model_base_url` | string | - | Base URL for API |
| `ai_model_timeout` | int | 60 | Request timeout (seconds) |
| `otel_enabled` | bool | true | Enable OpenTelemetry |
| `otel_endpoint` | string | - | OTLP endpoint |

## See Also

- [App Builder Guide](../guides/app-builder.md) - How to use configuration
- [Getting Started](../guides/getting-started.md) - Initial setup
