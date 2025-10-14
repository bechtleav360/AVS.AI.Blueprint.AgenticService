# Agent Configuration

**Quick reference for agent-specific configuration**

This guide covers agent-specific settings. For detailed configuration management and observability, see the specialized guides below.

## Related Guides

- **[Dynaconf](dynaconf.md)** - Configuration management system (settings files, environment variables, validation)
- **[OpenTelemetry](opentelemetry.md)** - Distributed tracing and observability configuration
- **[Dapr Configuration](dapr-configuration.md)** - Event processing and pub/sub setup

## Quick Start

### Minimal Configuration

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

### Complete Configuration

```toml
# custom/settings.toml
[default]
# Application
app_name = "invoice-processor"
app_port = 8001
log_level = "INFO"

# AI Model
ai_model_provider = "openai"
ai_model_name = "gpt-4"
ai_model_timeout = 60
ai_model_max_retries = 3

# Data Gateway (for thin events)
data_gateway_base_url = "https://gateway.example.com"
data_gateway_timeout = 30
data_gateway_max_retries = 3

# Observability (see OpenTelemetry guide)
otel_enabled = true
otel_service_name = "invoice-processor"
otel_endpoint = "http://localhost:4317"

[development]
log_level = "DEBUG"
ai_model_timeout = 120

[production]
log_level = "WARNING"
```

## AI Model Configuration

### OpenAI

```toml
[default]
ai_model_provider = "openai"
ai_model_name = "gpt-4"  # or gpt-4-turbo, gpt-3.5-turbo
ai_model_timeout = 60
ai_model_max_retries = 3
```

```toml
# secrets.toml
[default]
ai_model_api_key = "sk-proj-..."
```

**Available Models:**
- `gpt-4` - Most capable
- `gpt-4-turbo` - Faster, cheaper
- `gpt-3.5-turbo` - Fast, economical

### vLLM (Self-Hosted)

```toml
[default]
ai_model_provider = "vllm"
ai_model_name = "default"
ai_model_timeout = 120
```

```toml
# secrets.toml
[default]
ai_model_base_url = "https://your-vllm-server.com/v1"
ai_model_api_key = "your-vllm-key"
```

**vLLM-Specific:**
```bash
export AI_MODEL_TOOL_CALL_PARSER="hermes"
export AI_MODEL_MAX_TOKENS=4096
```

### Anthropic

```toml
[default]
ai_model_provider = "anthropic"
ai_model_name = "claude-3-opus-20240229"
ai_model_timeout = 60
```

```toml
# secrets.toml
[default]
ai_model_api_key = "sk-ant-..."
```

## Application Settings

### Basic Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `app_name` | string | "agent" | Service name |
| `app_port` | int | 8001 | HTTP port |
| `log_level` | string | "INFO" | DEBUG, INFO, WARNING, ERROR |

### Logging

```toml
[default]
log_level = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL

[development]
log_level = "DEBUG"

[production]
log_level = "WARNING"
```

**Environment variable:**
```bash
export LOG_LEVEL="DEBUG"
```

## Data Gateway Configuration

For thin event processing (fetch full data from gateway):

```toml
[default]
data_gateway_base_url = "https://gateway.example.com"
data_gateway_timeout = 30
data_gateway_max_retries = 3
data_gateway_circuit_breaker_threshold = 5
data_gateway_circuit_breaker_timeout = 60
```

```toml
# secrets.toml
[default]
data_gateway_api_key = "your-gateway-key"
```

**Circuit Breaker:**
- After 5 failures, circuit opens
- Waits 60 seconds before retry
- Prevents cascading failures

## Environment-Specific Configuration

### Development

```toml
[development]
log_level = "DEBUG"
ai_model_timeout = 120
otel_enabled = false  # Disable tracing locally
```

Run with:
```bash
export ENVIRONMENT=development
python -m uvicorn custom.src.main:app --reload
```

### Production

```toml
[production]
log_level = "WARNING"
ai_model_timeout = 60
otel_enabled = true
otel_endpoint = "https://otel-collector.prod.example.com"
```

Run with:
```bash
export ENVIRONMENT=production
python -m uvicorn custom.src.main:app --workers 4
```

## Custom Configuration

### Add Custom Settings

```toml
[default]
# Your custom settings
max_invoice_amount = 100000
enable_email_notifications = true
notification_email = "alerts@example.com"
```

**Access in code:**
```python
from base.src.config import Config

config = Config()
max_amount = config.get("max_invoice_amount")
email_enabled = config.get("enable_email_notifications")
```

### Nested Configuration

```toml
[default.email]
enabled = true
smtp_host = "smtp.example.com"
smtp_port = 587
from_address = "noreply@example.com"

[default.cache]
enabled = true
ttl = 3600
max_size = 1000
```

**Access:**
```python
email_config = config.get("email")
smtp_host = email_config["smtp_host"]
```

## Configuration Validation

### Validate on Startup

```python
# In custom/src/main.py
from base.src.app_builder import AppBuilder

builder = AppBuilder()
config = builder.config

# Validate required settings
required = ["ai_model_api_key", "app_name"]
missing = [key for key in required if not config.get(key)]

if missing:
    raise ValueError(f"Missing required configuration: {', '.join(missing)}")

app = builder.build()
```

## Configuration Reference

### All Agent Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| **Application** | | | |
| `app_name` | string | "agent" | Service name |
| `app_port` | int | 8001 | HTTP port |
| `log_level` | string | "INFO" | Log level |
| **AI Model** | | | |
| `ai_model_provider` | string | "openai" | Provider (openai, vllm, anthropic) |
| `ai_model_name` | string | "gpt-4" | Model name |
| `ai_model_api_key` | string | - | API key (required, in secrets.toml) |
| `ai_model_base_url` | string | - | Base URL (optional) |
| `ai_model_timeout` | int | 60 | Request timeout (seconds) |
| `ai_model_max_retries` | int | 3 | Max retry attempts |
| **Data Gateway** | | | |
| `data_gateway_base_url` | string | - | Gateway URL |
| `data_gateway_api_key` | string | - | API key (in secrets.toml) |
| `data_gateway_timeout` | int | 30 | Request timeout |
| `data_gateway_max_retries` | int | 3 | Max retries |
| **Observability** | | | |
| `otel_enabled` | bool | true | Enable OpenTelemetry |
| `otel_service_name` | string | - | Service name for traces |
| `otel_endpoint` | string | - | OTLP endpoint |

For complete OpenTelemetry settings, see [OpenTelemetry Configuration](opentelemetry.md).

## Best Practices

### 1. Never Commit Secrets

```bash
# .gitignore
secrets.toml
.secrets.*
.env
*.key
```

### 2. Use Environment Variables for Secrets

```bash
export AI_MODEL_API_KEY="sk-prod-key"
export DATA_GATEWAY_API_KEY="gateway-key"
```

### 3. Provide Defaults

```python
timeout = config.get("ai_model_timeout", 60)
log_level = config.get("log_level", "INFO")
```

### 4. Validate on Startup

```python
required = ["ai_model_api_key", "app_name"]
for key in required:
    if not config.get(key):
        raise ValueError(f"Missing: {key}")
```

### 5. Document Settings

```toml
# Maximum invoice amount to process (in EUR)
# Values above this will be flagged for manual review
max_invoice_amount = 100000
```

## Troubleshooting

### Configuration Not Loading

1. Check file exists: `ls -la custom/settings.toml`
2. Validate TOML: `python -c "import tomli; tomli.load(open('custom/settings.toml', 'rb'))"`
3. Check working directory

See [Dynaconf guide](dynaconf.md#troubleshooting) for detailed troubleshooting.

### AI Model Not Connecting

1. Check API key: `echo $AI_MODEL_API_KEY`
2. Test endpoint: `curl https://api.openai.com/v1/models -H "Authorization: Bearer $AI_MODEL_API_KEY"`
3. Check timeout settings

### Environment Variables Not Working

1. Variable exported: `echo $APP_NAME`
2. Correct naming: Use uppercase with underscores
3. Application restarted

See [Dynaconf guide](dynaconf.md#troubleshooting) for more details.

## Example Configurations

### Development

```toml
# settings.toml
[development]
app_name = "invoice-processor-dev"
log_level = "DEBUG"
ai_model_timeout = 120
otel_enabled = false
```

```bash
export ENVIRONMENT=development
export AI_MODEL_API_KEY="sk-dev-key"
cd custom && ./start_with_dapr.sh
```

### Production

```toml
# settings.toml
[production]
app_name = "invoice-processor"
log_level = "WARNING"
ai_model_timeout = 60
otel_enabled = true
otel_endpoint = "https://otel-collector.prod.example.com"
data_gateway_base_url = "https://gateway.prod.example.com"
```

```bash
export ENVIRONMENT=production
export AI_MODEL_API_KEY="sk-prod-key"
export DATA_GATEWAY_API_KEY="prod-gateway-key"
kubectl apply -f k8s/
```

## See Also

- **[Dynaconf](dynaconf.md)** - Configuration management in depth
- **[OpenTelemetry](opentelemetry.md)** - Observability configuration
- **[Dapr Configuration](dapr-configuration.md)** - Event processing setup
- **[Getting Started](../getting-started.md)** - Initial setup
- **[Deployment Guide](../deployment.md)** - Production deployment

## Multi-Runtime Configuration

The framework supports multiple agent runtime instances with different configurations, allowing specialized agents for different purposes.

### Overview

Each runtime can have its own:
- System prompts
- Instruction prompts  
- AI models and parameters
- Usage limits
- Providers (mix OpenAI and vLLM)

### Configuration Structure

```toml
[default]
# Global defaults
ai_model_provider = "vllm"
ai_model_base_url = "https://avs-vllm.q14.net/v1"

# Runtime-specific configurations
[runtime.invoice_analyzer]
system_prompt_name = "invoice_system"
instruction_prompt_name = "invoice_instruction"
ai_model_name = "invoice-specialized-model"
ai_model_temperature = 0.1
ai_model_max_tokens = 2000

[runtime.document_classifier]
system_prompt_name = "classifier_system"
ai_model_provider = "openai"
ai_model_name = "gpt-4"
ai_model_temperature = 0.0
```

### Registering Multiple Runtimes

```python
# custom/src/main.py
from base.src.app_builder import AppBuilder
from .agent.runtime import AgentRuntime

app = (
    AppBuilder(settings_files=settings_files, root_path=project_root)
    .with_agent_runtime(AgentRuntime, name="invoice_analyzer", is_default=True)
    .with_agent_runtime(AgentRuntime, name="document_classifier")
    .with_agent_runtime(AgentRuntime, name="summarizer")
    .build()
)
```

### Runtime-Specific Settings

All these can be set in `[runtime.{name}]` sections:

**AI Model:**
- `ai_model_provider` - Provider name
- `ai_model_name` - Model identifier
- `ai_model_base_url` - API base URL
- `ai_model_max_tokens` - Max tokens per request
- `ai_model_temperature` - Temperature (0.0-1.0)

**Prompts:**
- `system_prompt_name` - System prompt file name
- `instruction_prompt_name` - Instruction prompt file name
- `prompt_directory` - Custom prompt directory
- `prompt_search_paths` - Additional search paths

**Usage Limits:**
- `ai_usage_request_limit` - Max requests per run
- `ai_usage_input_tokens_limit` - Max input tokens
- `ai_usage_output_tokens_limit` - Max output tokens

### Use Cases

**Task-Specific Runtimes:**
```toml
[runtime.invoice_analyzer]
ai_model_temperature = 0.1  # Precise
ai_model_max_tokens = 2000

[runtime.creative_writer]
ai_model_temperature = 0.9  # Creative
ai_model_max_tokens = 4000
```

**Multi-Language:**
```toml
[runtime.english_analyzer]
system_prompt_name = "system_en"
prompt_directory = "/etc/agent/prompts/en"

[runtime.german_analyzer]
system_prompt_name = "system_de"
prompt_directory = "/etc/agent/prompts/de"
```

**Provider Mixing:**
```toml
[runtime.fast_classifier]
ai_model_provider = "vllm"
ai_model_name = "fast-local-model"

[runtime.quality_analyzer]
ai_model_provider = "openai"
ai_model_name = "gpt-4"
```

## Prompt Configuration

### Prompt File Locations

Configure where prompts are loaded from:

```toml
[default]
# Custom directory for prompt files
prompt_directory = "/etc/agent/prompts"

# Additional search paths
prompt_search_paths = [
    "/mnt/configmap/prompts",
    "../shared/prompts"
]

# Prompt file names
system_prompt_name = "system"
instruction_prompt_name = "instruction"
```

### Search Order

The framework searches for prompts in this order:
1. Custom path from `prompt_directory`
2. Additional paths from `prompt_search_paths`
3. Default locations based on agent class location

### Kubernetes ConfigMap Example

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: agent-prompts
data:
  system.prompt: |
    You are an AI assistant specialized in invoice processing...
  
  instruction.prompt: |
    Analyze this invoice and extract the information:
    
    {invoice_text}
---
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
      - name: agent
        volumeMounts:
        - name: prompts
          mountPath: /etc/agent/prompts
      volumes:
      - name: prompts
        configMap:
          name: agent-prompts
```

Then configure:
```toml
[production]
prompt_directory = "/etc/agent/prompts"
```

### Instruction Prompt Templates

Instruction prompts support template variables:

```
# custom/src/prompts/instruction.prompt
Analyze this invoice and extract the information:

{invoice_text}

Please extract all relevant invoice details including:
- Invoice number and date
- Customer information
- Line items with quantities and prices
```

Use in code:
```python
# Automatically loaded and formatted
instruction = self._load_and_format_instruction(
    fallback_template="Default template: {invoice_text}",
    invoice_text=invoice_data
)
```

### Runtime-Specific Prompts

Each runtime can use different prompts:

```toml
[runtime.invoice_analyzer]
system_prompt_name = "invoice_system"
instruction_prompt_name = "invoice_instruction"

[runtime.document_classifier]
system_prompt_name = "classifier_system"
instruction_prompt_name = "classifier_instruction"
```

Organize prompts:
```
custom/src/prompts/
├── invoice_system.prompt
├── invoice_instruction.prompt
├── classifier_system.prompt
└── classifier_instruction.prompt
```

