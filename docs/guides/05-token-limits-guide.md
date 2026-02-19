# Agent Configuration Guide: Using Runtime Config for Token Limits

## Overview

The Agents Blueprint framework **automatically applies `model_max_tokens` configuration** to agent API calls through the `AgentRuntime.run()` method. This guide explains how to configure and verify token limits are working correctly.

## How It Works

### Architecture

1. **Configuration Loading** (`Config.get_ai_config()`)
   - Reads `model_max_tokens` from runtime-specific config or global defaults
   - Returns `AIConfig` Pydantic model with `max_tokens` field

2. **Agent Building** (`AgentBuilder.build()`)
   - Calls `get_model_settings()` to extract model configuration
   - Stores settings in `AgentRuntime._model_settings`

3. **Agent Execution** (`AgentRuntime.run()`)
   - Automatically applies `_model_settings` to Pydantic AI's `model_settings` parameter
   - Passes `max_tokens` to the LLM provider's API call

### Code Flow

```
settings.toml (model_max_tokens: 6000)
    ↓
Config.get_ai_config("extract")
    ↓
AIConfig(max_tokens=6000)
    ↓
AgentBuilder.get_model_settings()
    ↓
ModelSettings(max_tokens=6000)
    ↓
AgentRuntime._model_settings
    ↓
AgentRuntime.run() → model_settings={"max_tokens": 6000}
    ↓
LLM API Call (OpenAI, vLLM, etc.)
```

## Configuration

### 1. Settings File Configuration

In `settings.toml`, configure `model_max_tokens` for each runtime:

```toml
# Global default (applies to all runtimes unless overridden)
model_max_tokens = 4096

# Runtime-specific overrides
[default.runtimes.extract]
model_provider = "openai"
model_name = "gpt-4o-mini"
model_max_tokens = 6000

[default.runtimes.decompose]
model_provider = "openai"
model_name = "gpt-4o-mini"
model_max_tokens = 6000

[default.runtimes.search]
model_provider = "openai"
model_name = "gpt-4o-mini"
model_max_tokens = 2000

[default.runtimes.evaluator]
model_provider = "openai"
model_name = "gpt-4o-mini"
model_max_tokens = 5000
```

### 2. Environment Variable Overrides

Override configuration via environment variables (takes precedence over `settings.toml`):

```bash
# Extract runtime
export DYNACONF_RUNTIMES__EXTRACT__MODEL_MAX_TOKENS="6000"

# Decompose runtime
export DYNACONF_RUNTIMES__DECOMPOSE__MODEL_MAX_TOKENS="6000"

# Search runtime
export DYNACONF_RUNTIMES__SEARCH__MODEL_MAX_TOKENS="2000"

# Relevance gate runtime
export DYNACONF_RUNTIMES__RELEVANCE_GATE__MODEL_MAX_TOKENS="2000"

# Evaluator runtime
export DYNACONF_RUNTIMES__EVALUATOR__MODEL_MAX_TOKENS="5000"

# Summarize runtime
export DYNACONF_RUNTIMES__SUMMARIZE__MODEL_MAX_TOKENS="2000"

# Rerank runtime
export DYNACONF_RUNTIMES__RERANK__MODEL_MAX_TOKENS="2000"
```

### 3. Agent Builder Configuration

In `main.py`, agents are configured to automatically use token limits from config:

```python
from blueprint.agents import AppBuilder, AgentBuilder, Config
from pathlib import Path

# Load configuration (automatically initializes logging)
config = Config(
    settings_files=["settings.toml", "secrets.toml"],
    root_path=Path(__file__).parent.parent,
)

# Build agent with automatic token limit configuration
agents_extract = (
    AgentBuilder(config, runtime_name="extract")
    .with_model_from_config()  # Reads model_max_tokens from config
    .with_system_prompt("extract_instruction")
    .build(name="agents-extract")
)

# The agent now has model_settings with max_tokens=6000
# These are automatically applied in agent.run() calls
```

## Verification

### 1. Check Configuration Loading

Add logging to verify the config is loaded correctly:

```python
from blueprint.agents import Config
from pathlib import Path

config = Config(
    settings_files=["settings.toml"],
    root_path=Path(__file__).parent.parent,
)

# Get AI config for extract runtime
ai_config = config.get_ai_config("extract")
print(f"Extract runtime config:")
print(f"  Provider: {ai_config.provider}")
print(f"  Model: {ai_config.model_name}")
print(f"  Max tokens: {ai_config.max_tokens}")
```

**Expected output:**
```
Extract runtime config:
  Provider: openai
  Model: gpt-4o-mini
  Max tokens: 6000
```

### 2. Check Agent Model Settings

After building the agent, verify model settings are configured:

```python
from blueprint.agents import AgentBuilder, Config
from pathlib import Path

config = Config(
    settings_files=["settings.toml"],
    root_path=Path(__file__).parent.parent,
)

agent = (
    AgentBuilder(config, runtime_name="extract")
    .with_model_from_config()
    .with_system_prompt("extract_instruction")
    .build(name="agents-extract")
)

# Check model settings
model_settings = agent.get_model_settings()
print(f"Agent model settings: {model_settings}")
```

**Expected output:**
```
Agent model settings: {'max_tokens': 6000}
```

### 3. Monitor API Calls

Add logging to see what parameters are sent to the LLM API:

```python
import logging

# Enable debug logging for the agent module
logging.getLogger("blueprint.agents").setLevel(logging.DEBUG)

# Now when you run the agent, you'll see:
# DEBUG: Model settings: max_tokens=6000
# DEBUG: Model settings: temperature=0.7
```

### 4. Test with Agent Execution

Execute the agent and verify token limits are applied:

```python
import asyncio
from blueprint.agents import AgentBuilder, Config
from pathlib import Path

async def test_agent():
    config = Config(
        settings_files=["settings.toml"],
        root_path=Path(__file__).parent.parent,
    )

    agent = (
        AgentBuilder(config, runtime_name="extract")
        .with_model_from_config()
        .with_system_prompt("extract_instruction")
        .build(name="agents-extract")
    )

    # Run agent - max_tokens is automatically applied
    result = await agent.run("Extract key information from this document...")

    # Check usage
    usage = result.usage
    print(f"Tokens used: {usage.request_tokens if hasattr(usage, 'request_tokens') else 'N/A'}")

asyncio.run(test_agent())
```

## How Token Limits Are Applied

### In AgentBuilder

The `get_model_settings()` method extracts token limits from configuration:

```python
def get_model_settings(self) -> ModelSettings:
    """Get model settings for use in agent.run() calls."""
    ai_config = self._config.get_ai_config(self._runtime_name)
    settings: ModelSettings = {}

    if ai_config.max_tokens is not None:
        settings["max_tokens"] = ai_config.max_tokens
        logger.debug("Model settings: max_tokens=%d", ai_config.max_tokens)

    if ai_config.temperature is not None:
        settings["temperature"] = ai_config.temperature
        logger.debug("Model settings: temperature=%.2f", ai_config.temperature)

    return settings
```

### In AgentRuntime

The `run()` method automatically applies model settings:

```python
async def run(
    self,
    user_prompt: str | None = None,
    *,
    model_settings: ModelSettings | None = None,
    **kwargs: Any,
) -> AgentRunResult:
    """Execute the agent with automatic model settings from configuration."""

    # Use provided model_settings, or fall back to configuration settings
    if model_settings is None:
        model_settings = self.get_model_settings()

    # Call parent run() with model_settings
    return await super().run(user_prompt, model_settings=model_settings, **kwargs)
```

## Configuration Priority

Token limits are resolved in this order (first match wins):

1. **Explicit parameter in `agent.run()` call** (highest priority)
   ```python
   result = await agent.run(
       "prompt",
       model_settings={"max_tokens": 8000}  # Override
   )
   ```

2. **Runtime-specific config** (e.g., `runtimes.extract.model_max_tokens`)
   ```toml
   [default.runtimes.extract]
   model_max_tokens = 6000
   ```

3. **Environment variable override** (e.g., `DYNACONF_RUNTIMES__EXTRACT__MODEL_MAX_TOKENS`)
   ```bash
   export DYNACONF_RUNTIMES__EXTRACT__MODEL_MAX_TOKENS="6000"
   ```

4. **Global config** (e.g., `model_max_tokens = 4096`)
   ```toml
   model_max_tokens = 4096
   ```

5. **LLM provider default** (lowest priority)

## Debugging

### Enable Debug Logging

```python
import logging

# Enable debug logging for configuration and agent modules
logging.basicConfig(level=logging.DEBUG)
logging.getLogger("blueprint.agents.config").setLevel(logging.DEBUG)
logging.getLogger("blueprint.agents.agent").setLevel(logging.DEBUG)
```

### Check Configuration Resolution

```python
from blueprint.agents import Config
from pathlib import Path

config = Config(
    settings_files=["settings.toml"],
    root_path=Path(__file__).parent.parent,
)

# Check what the config resolved to
for runtime_name in ["extract", "decompose", "search"]:
    ai_config = config.get_ai_config(runtime_name)
    print(f"{runtime_name}: max_tokens={ai_config.max_tokens}")
```

### Verify Environment Variables

```bash
# Check if environment variables are set
echo $DYNACONF_RUNTIMES__EXTRACT__MODEL_MAX_TOKENS

# Check all DYNACONF variables
env | grep DYNACONF
```

### Test Configuration Loading

```python
from blueprint.agents import Config
from pathlib import Path
import json

config = Config(
    settings_files=["settings.toml"],
    root_path=Path(__file__).parent.parent,
)

# Get raw settings
settings = config.settings
print(json.dumps(settings.get("runtimes", {}), indent=2))
```

## Common Issues and Solutions

### Issue: Token Limits Not Applied

**Symptom:** Agent uses LLM provider's default token limits instead of configured values.

**Solution:**
1. Verify `model_max_tokens` is set in `settings.toml`
2. Check environment variables: `echo $DYNACONF_RUNTIMES__EXTRACT__MODEL_MAX_TOKENS`
3. Enable debug logging to see what config was loaded
4. Verify agent is built with `.with_model_from_config()`

### Issue: Configuration Not Found

**Symptom:** `ValueError: AI configuration must specify 'provider'`

**Solution:**
1. Ensure `settings.toml` exists and is readable
2. Verify runtime name matches: `AgentBuilder(config, runtime_name="extract")`
3. Check that `[default.runtimes.extract]` section exists in settings
4. Verify `model_provider` is set (e.g., `model_provider = "openai"`)

### Issue: Environment Variable Override Not Working

**Symptom:** Environment variable is set but not being used.

**Solution:**
1. Verify variable name format: `DYNACONF_RUNTIMES__EXTRACT__MODEL_MAX_TOKENS`
2. Ensure variable is exported: `export DYNACONF_RUNTIMES__EXTRACT__MODEL_MAX_TOKENS="6000"`
3. Verify Config is initialized AFTER setting environment variable
4. Check that settings file path is correct

### Issue: Token Limit Error from LLM

**Symptom:** LLM returns error like "Tokens exceed maximum"

**Solution:**
1. Check if `model_max_tokens` is set too high for the model
2. Verify the model supports the configured token limit
3. Check LLM provider's documentation for max tokens per model
4. Consider reducing `model_max_tokens` or using a different model

## Best Practices

### 1. Use Runtime-Specific Configuration

```toml
# ✅ Good: Different limits for different runtimes
[default.runtimes.extract]
model_max_tokens = 6000

[default.runtimes.search]
model_max_tokens = 2000
```

### 2. Set Global Default

```toml
# ✅ Good: Fallback for runtimes without specific config
model_max_tokens = 4096

[default.runtimes.extract]
model_max_tokens = 6000  # Override for this runtime
```

### 3. Use Environment Variables for Deployment

```bash
# ✅ Good: Override in production without changing code
export DYNACONF_RUNTIMES__EXTRACT__MODEL_MAX_TOKENS="8000"
```

### 4. Enable Debug Logging in Development

```python
# ✅ Good: See what configuration is being used
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 5. Test Configuration Before Deployment

```python
# ✅ Good: Verify config is correct before running agents
from blueprint.agents import Config

config = Config(settings_files=["settings.toml"])
ai_config = config.get_ai_config("extract")
assert ai_config.max_tokens == 6000, "Token limit not configured correctly"
```

## Reference

### Configuration Fields

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `model_max_tokens` | `int` | Maximum tokens per request | `6000` |
| `model_temperature` | `float` | Temperature for generation (0-2) | `0.7` |
| `model_provider` | `str` | LLM provider name | `"openai"` |
| `model_name` | `str` | Model identifier | `"gpt-4o-mini"` |
| `model_api_key` | `str` | API key for provider | `"sk-..."` |
| `model_base_url` | `str` | Base URL for API | `"https://api.openai.com/v1"` |

### Environment Variable Format

```
DYNACONF_RUNTIMES__<RUNTIME_NAME>__<FIELD_NAME>

Examples:
DYNACONF_RUNTIMES__EXTRACT__MODEL_MAX_TOKENS
DYNACONF_RUNTIMES__EXTRACT__MODEL_NAME
DYNACONF_RUNTIMES__SEARCH__MODEL_MAX_TOKENS
```

### ModelSettings Type

```python
from pydantic_ai.settings import ModelSettings

# ModelSettings is a TypedDict with these optional fields:
# - max_tokens: int | None
# - temperature: float | None
# - top_p: float | None
# - top_k: int | None
# - frequency_penalty: float | None
# - presence_penalty: float | None
# - allow_text_completions: bool | None
```

## Summary

The Agents Blueprint framework **automatically applies token limits** configured in `settings.toml` or environment variables. The flow is:

1. **Configure** token limits in `settings.toml` or environment variables
2. **Build** agent with `AgentBuilder(config).with_model_from_config()`
3. **Execute** agent with `await agent.run(prompt)` - token limits are automatically applied
4. **Verify** by checking logs or using `agent.get_model_settings()`

No additional code is needed to apply token limits - the framework handles it automatically.
