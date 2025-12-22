# Multi-Agent Configuration Guide

This guide explains how to configure multiple agents with different models and settings in the Blueprint Agents framework.

## Configuration Patterns

The framework supports **two configuration patterns** for backward compatibility:

### 1. New Pattern (Recommended for Runtime-Specific Configs)

Use the cleaner `model_*` prefix for runtime-specific agent configurations:

```toml
[default.runtimes.junior_support]
model_provider = "vllm"
model_base_url = "https://avs-vllm.q14.net/v1"
model_name = "Qwen/Qwen2.5-7B-Instruct"
model_max_tokens = 2000
model_temperature = 0.7
prompt_directory = "src/prompts"
system_prompt_name = "junior_system"

[default.runtimes.senior_support]
model_provider = "vllm"
model_base_url = "https://avs-vllm.q14.net/v1"
model_name = "Qwen/Qwen2.5-32B-Instruct"
model_max_tokens = 200
model_temperature = 0.2
prompt_directory = "src/prompts"
system_prompt_name = "senior_system"
```

### 2. Old Pattern (Still Supported)

Use the `ai_model_*` prefix for global defaults or runtime-specific configs:

```toml
[default]
ai_model_provider = "vllm"
ai_model_base_url = "https://avs-vllm.q14.net/v1"
ai_model_name = "default"
ai_model_max_tokens = 500
ai_model_temperature = 0.1

[default.runtimes.trivia_master]
model_provider = "openai"
model_name = "gpt-4o-mini"
prompt_directory = "src/prompts"
system_prompt_name = "system"
```

## Fallback Behavior

The configuration system uses the following priority order:

1. **Runtime-specific new pattern** (`model_*` in `[default.runtimes.<name>]`)
2. **Runtime-specific old pattern** (`ai_model_*` in `[default.runtimes.<name>]`)
3. **Global old pattern** (`ai_model_*` in `[default]`)

This ensures:
- ✅ New examples can use the cleaner `model_*` pattern
- ✅ Old examples continue to work with `ai_model_*` pattern
- ✅ Global defaults provide fallback values

## Multi-Agent Example

Here's how to configure two agents with different models:

**settings.toml:**
```toml
[default]
app_name = "Customer Support Q&A"

[default.runtimes.junior_support]
model_provider = "vllm"
model_name = "Qwen/Qwen2.5-7B-Instruct"
model_max_tokens = 2000
model_temperature = 0.7
prompt_directory = "src/prompts"
system_prompt_name = "junior_system"

[default.runtimes.senior_support]
model_provider = "vllm"
model_name = "Qwen/Qwen2.5-32B-Instruct"
model_max_tokens = 200
model_temperature = 0.2
prompt_directory = "src/prompts"
system_prompt_name = "senior_system"
```

**main.py:**
```python
from pathlib import Path
from blueprint.agents.agent import AgentBuilder
from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.config import Config

config = Config(
    settings_files=["settings.toml", "secrets.toml"],
    root_path=Path(__file__).parent.parent,
)

# Build junior agent
junior_agent = (
    AgentBuilder(config, runtime_name="junior_support")
    .with_model_from_config("junior_support")
    .with_system_prompt("junior_system")
    .build(name="junior_support")
)

# Build senior agent
senior_agent = (
    AgentBuilder(config, runtime_name="senior_support")
    .with_model_from_config("senior_support")
    .with_system_prompt("senior_system")
    .build(name="senior_support")
)

# Build app with both agents
app = (
    AppBuilder(config=config)
    .with_cache()
    .with_agent(junior_agent)
    .with_agent(senior_agent)
    .with_service(YourService())
    .with_rest_api(YourRestApi())
    .build()
)
```

## Configuration Keys

### Model Configuration

| New Pattern | Old Pattern | Description |
|------------|-------------|-------------|
| `model_provider` | `ai_model_provider` | Model provider (e.g., "vllm", "openai") |
| `model_name` | `ai_model_name` | Model name/identifier |
| `model_base_url` | `ai_model_base_url` | Base URL for API |
| `model_api_key` | `ai_model_api_key` | API key (use secrets.toml) |
| `model_max_tokens` | `ai_model_max_tokens` | Maximum output tokens |
| `model_temperature` | `ai_model_temperature` | Temperature (0.0-2.0) |

### Prompt Configuration

| Key | Description |
|-----|-------------|
| `prompt_directory` | Directory containing prompt files |
| `system_prompt_name` | Name of system prompt file (without .prompt) |

### Usage Limits

| New Pattern | Old Pattern | Description |
|------------|-------------|-------------|
| `concurrent_requests` | `ai_concurrent_requests` | Max concurrent requests |
| `usage_request_limit` | `ai_usage_request_limit` | Request count limit |
| `usage_input_tokens_limit` | `ai_usage_input_tokens_limit` | Input token limit |
| `usage_output_tokens_limit` | `ai_usage_output_tokens_limit` | Output token limit |
| `usage_total_tokens_limit` | `ai_usage_total_tokens_limit` | Total token limit |

## Best Practices

1. **Use runtime-specific configs** for multi-agent systems
2. **Use the new `model_*` pattern** for cleaner configuration
3. **Keep global defaults** for common settings
4. **Use descriptive runtime names** (e.g., "junior_support", "senior_support")
5. **Store API keys in secrets.toml**, not settings.toml

## Examples

- **Single Agent (Old Pattern)**: `examples/trivia_game/`
- **Multi-Agent (New Pattern)**: `examples/customer_support_qa/`
