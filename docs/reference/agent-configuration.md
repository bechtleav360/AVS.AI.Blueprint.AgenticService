# Agent Configuration Guide

This guide explains how to build and configure AI agents using the Blueprint Agents framework, including model settings, prompts, tools, and runtime configuration.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Building an Agent](#building-an-agent)
3. [Configuration Options](#configuration-options)
4. [Model Settings](#model-settings)
5. [System Prompts](#system-prompts)
6. [Tools and Dependencies](#tools-and-dependencies)
7. [Multiple Runtimes](#multiple-runtimes)
8. [Troubleshooting](#troubleshooting)
9. [API Reference](#api-reference)

## Quick Start

### Minimal Agent

```python
from blueprint.agents import AgentBuilder, Config
from pathlib import Path

# Load configuration
config = Config(
    settings_files=["settings.toml"],
    root_path=Path(__file__).parent.parent,
)

# Build agent
agent = (
    AgentBuilder(config)
    .with_model_from_config()
    .with_system_prompt("You are a helpful assistant")
    .build()
)

# Use agent
result = await agent.run("What is Python?")
```

### Agent with Model Settings

```python
# Get model settings from configuration
model_settings = agent.get_model_settings()

# Call agent with settings applied
result = await agent.run(
    "Extract information from this text...",
    model_settings=model_settings
)
```

## Building an Agent

### Step 1: Initialize the Builder

```python
from blueprint.agents import AgentBuilder, Config

config = Config(settings_files=["settings.toml"])
builder = AgentBuilder(config, runtime_name="extract")
```

**Parameters:**
- `config` (Config): Application configuration
- `runtime_name` (str): Name of the runtime configuration section (default: "default")
- `meter` (optional): OpenTelemetry Meter for metrics
- `package_root` (optional): Root path for locating prompts

### Step 2: Configure the Model

**Option A: From Configuration**

```python
builder.with_model_from_config()
```

Uses `model_provider`, `model_name`, and `model_api_key` from your runtime config.

**Option B: Explicit Model Name**

```python
builder.with_model("gpt-4o-mini")
```

Overrides the model name while keeping other config settings.

### Step 3: Set System Prompt

**Option A: Inline Text**

```python
builder.with_system_prompt("You are an information extraction assistant")
```

**Option B: From File**

```python
builder.with_system_prompt("system")  # Loads from system.prompt file
```

**Option C: Auto-load from Config**

```python
builder.with_system_prompt()  # Uses system_prompt_name from config
```

### Step 4: Add Tools (Optional)

```python
from pydantic_ai import Tool

def calculate(expression: str) -> str:
    """Calculate a mathematical expression."""
    return str(eval(expression))

builder.with_tool("calculate", calculate)
```

### Step 5: Configure Result Type (Optional)

```python
from pydantic import BaseModel

class ExtractionResult(BaseModel):
    title: str
    summary: str
    keywords: list[str]

builder.with_result_type(ExtractionResult)
```

### Step 6: Build the Agent

```python
agent = builder.build()
```

Returns an `AgentRuntime` instance ready to use.

## Configuration Options

### In settings.toml

```toml
# Global defaults
model_provider = "openai"
model_name = "gpt-4o-mini"
model_api_key = "${OPENAI_API_KEY}"
model_max_tokens = 4000
model_temperature = 0.7

# Runtime-specific overrides
[runtimes.extract]
model_name = "gpt-4o"
model_max_tokens = 2000
model_temperature = 0.3

[runtimes.generate]
model_max_tokens = 4000
model_temperature = 0.9
```

### Configuration Keys

| Key | Type | Description |
|-----|------|-------------|
| `model_provider` | string | AI provider: "openai", "vllm", etc. |
| `model_name` | string | Model identifier (e.g., "gpt-4o-mini") |
| `model_api_key` | string | API key for the provider |
| `model_base_url` | string | Base URL for API (optional) |
| `model_max_tokens` | int | Maximum tokens to generate |
| `model_temperature` | float | Randomness (0.0-2.0) |
| `system_prompt_name` | string | System prompt file name |
| `prompt_directory` | string | Custom prompt directory |

## Model Settings

### What Are Model Settings?

Model settings are runtime parameters passed to each `agent.run()` call. They control how the model generates responses.

### Getting Model Settings

```python
from pydantic_ai.settings import ModelSettings

# From agent
model_settings: ModelSettings = agent.get_model_settings()
# Returns: {"max_tokens": 4000, "temperature": 0.7}

# From builder
builder = AgentBuilder(config)
builder.with_model_from_config()
model_settings: ModelSettings = builder.get_model_settings()
```

### Passing Model Settings to agent.run()

```python
# Get settings from agent configuration
model_settings = agent.get_model_settings()

# Pass to agent.run()
result = await agent.run(
    "Your prompt here",
    model_settings=model_settings
)
```

### Available Settings

- **max_tokens** (int): Maximum tokens to generate
  - Short responses: 500-1000
  - Medium responses: 1000-2000
  - Long responses: 2000-4000
  - Very long responses: 4000+

- **temperature** (float): Randomness of responses
  - 0.0: Deterministic (best for analysis)
  - 0.5-0.7: Balanced (default)
  - 1.0+: Creative (best for generation)

### Why Model Settings Matter

**Problem:** Configuring `max_tokens` in settings.toml alone doesn't apply it to agent calls.

**Solution:** Pass model settings explicitly to `agent.run()`:

```python
# ❌ Wrong - settings not applied
result = await agent.run(prompt)

# ✅ Correct - settings applied
model_settings = agent.get_model_settings()
result = await agent.run(prompt, model_settings=model_settings)
```

## System Prompts

### Loading System Prompts

System prompts define the agent's behavior and role.

**From Inline Text:**
```python
builder.with_system_prompt("You are a helpful assistant")
```

**From File:**
```python
# Loads from prompts/system.prompt
builder.with_system_prompt("system")
```

**From Configuration:**
```python
# Uses system_prompt_name from config
builder.with_system_prompt()
```

### Prompt File Locations

The framework searches for prompts in this order:

1. Custom path: `prompt_directory` from config
2. Additional search paths: `prompt_search_paths` from config
3. Default: `src/prompts/` relative to package root

### Example Prompt File

**prompts/system.prompt:**
```
You are an expert information extraction assistant.

Your task is to:
1. Analyze the provided text
2. Extract key information
3. Return structured data

Be precise and concise in your responses.
```

## Tools and Dependencies

### Adding Tools

```python
from pydantic_ai import Tool

def search_web(query: str) -> str:
    """Search the web for information."""
    # Implementation here
    return results

builder.with_tool("search", search_web)
```

### Tool Signatures

Tools must have:
- Clear function name
- Type hints for parameters
- Docstring describing the tool
- Return type annotation

```python
def calculate(expression: str) -> float:
    """Calculate a mathematical expression."""
    return eval(expression)
```

### Using Tools in Prompts

```python
system_prompt = """
You are a calculator assistant. You have access to:
- calculate: Evaluate mathematical expressions

Use these tools to help answer questions.
"""

builder.with_system_prompt(system_prompt)
builder.with_tool("calculate", calculate)
```

## Multiple Runtimes

### Configuration

```toml
[runtimes.extract]
model_name = "gpt-4o"
model_max_tokens = 2000
model_temperature = 0.3

[runtimes.generate]
model_name = "gpt-4o-mini"
model_max_tokens = 4000
model_temperature = 0.9

[runtimes.summarize]
model_name = "gpt-4o-mini"
model_max_tokens = 1000
model_temperature = 0.5
```

### Building Multiple Agents

```python
# Extract agent - precise, deterministic
extract_agent = (
    AgentBuilder(config, runtime_name="extract")
    .with_model_from_config()
    .with_system_prompt("Extract structured data")
    .build()
)

# Generate agent - creative, longer responses
generate_agent = (
    AgentBuilder(config, runtime_name="generate")
    .with_model_from_config()
    .with_system_prompt("Generate creative content")
    .build()
)

# Summarize agent - concise, balanced
summarize_agent = (
    AgentBuilder(config, runtime_name="summarize")
    .with_model_from_config()
    .with_system_prompt("Summarize content")
    .build()
)
```

### Using Multiple Agents

```python
async def process_content(text: str):
    # Extract key information
    extract_settings = extract_agent.get_model_settings()
    extraction = await extract_agent.run(
        f"Extract from: {text}",
        model_settings=extract_settings
    )

    # Generate summary
    generate_settings = generate_agent.get_model_settings()
    summary = await generate_agent.run(
        f"Summarize: {extraction.data}",
        model_settings=generate_settings
    )

    return summary
```

## Complete Example

```python
from blueprint.agents import AgentBuilder, Config
from pydantic import BaseModel
from pathlib import Path

# Define output structure
class ExtractionResult(BaseModel):
    title: str
    summary: str
    keywords: list[str]
    entities: list[str]

# Load configuration
config = Config(
    settings_files=["settings.toml"],
    root_path=Path(__file__).parent.parent,
)

# Build agent
extraction_agent = (
    AgentBuilder(config, runtime_name="extract")
    .with_model_from_config()
    .with_system_prompt("You are an expert information extraction assistant")
    .with_result_type(ExtractionResult)
    .build()
)

# Use agent
async def extract_from_text(text: str) -> ExtractionResult:
    model_settings = extraction_agent.get_model_settings()

    result = await extraction_agent.run(
        f"Extract information from:\n\n{text}",
        model_settings=model_settings
    )

    return result.data
```

## Troubleshooting

### Error: "Model token limit exceeded"

**Cause:** `max_tokens` is too low for the response.

**Solution:** Increase `model_max_tokens` in settings:

```toml
[runtimes.extract]
model_max_tokens = 8000  # Increase from current value
```

### Error: "max_tokens not being applied"

**Cause:** Model settings not passed to `agent.run()`.

**Solution:** Always pass model settings:

```python
model_settings = agent.get_model_settings()
result = await agent.run(prompt, model_settings=model_settings)
```

### Error: "System prompt not found"

**Cause:** Prompt file doesn't exist or wrong path.

**Solution:** Verify prompt file exists:

```
src/prompts/system.prompt  # File must exist
```

Or use inline text:

```python
builder.with_system_prompt("You are helpful")
```

### Error: "Model not configured"

**Cause:** Model not set before building.

**Solution:** Configure model before building:

```python
builder.with_model_from_config()  # or .with_model("gpt-4o")
agent = builder.build()
```

### Error: "Runtime config not found"

**Cause:** Runtime name doesn't match config section.

**Solution:** Verify runtime name matches config:

```toml
[runtimes.extract]  # Config section
```

```python
AgentBuilder(config, runtime_name="extract")  # Must match
```

## API Reference

### AgentBuilder

#### with_model_from_config()

```python
def with_model_from_config(self, runtime_name: str | None = None) -> "AgentBuilder":
    """Configure model from runtime-specific config.

    Args:
        runtime_name: Runtime name to lookup config (uses builder's runtime_name if None)

    Returns:
        Self for chaining
    """
```

#### with_model()

```python
def with_model(self, model_name: str) -> "AgentBuilder":
    """Configure with a specific model name.

    Args:
        model_name: Model identifier (e.g., "gpt-4o-mini")

    Returns:
        Self for chaining
    """
```

#### with_system_prompt()

```python
def with_system_prompt(self, name: str | None = None) -> "AgentBuilder":
    """Configure the system prompt.

    Args:
        name: Prompt text or file name (None to load from config)

    Returns:
        Self for chaining
    """
```

#### with_tool()

```python
def with_tool(self, name: str, function: Callable) -> "AgentBuilder":
    """Add a single tool.

    Args:
        name: Tool name
        function: Tool function

    Returns:
        Self for chaining
    """
```

#### with_result_type()

```python
def with_result_type(self, result_type: type[BaseModel]) -> "AgentBuilder":
    """Configure the result type for structured outputs.

    Args:
        result_type: Pydantic model for results

    Returns:
        Self for chaining
    """
```

#### get_model_settings()

```python
def get_model_settings(self) -> ModelSettings:
    """Get model settings for use in agent.run() calls.

    Returns:
        ModelSettings object with configuration from runtime settings
    """
```

#### build()

```python
def build(self, **kwargs) -> AgentRuntime:
    """Build the configured agent.

    Returns:
        Configured AgentRuntime instance

    Raises:
        ValueError: If required configuration is missing
    """
```

### AgentRuntime

#### get_model_settings()

```python
def get_model_settings(self) -> dict[str, Any]:
    """Get model settings for use in agent.run() calls.

    Returns:
        Dictionary with model settings from configuration
    """
```

#### get_prompt()

```python
def get_prompt(self, prompt_name: str, path: str = "") -> str:
    """Load instruction prompt by name (lazy loading with caching).

    Args:
        prompt_name: Name of the prompt to load
        path: Optional path to load from

    Returns:
        Prompt content as string
    """
```

#### run()

```python
async def run(
    self,
    user_prompt: str,
    *,
    model_settings: ModelSettings | None = None,
    deps: Any = None,
    **kwargs: Any,
) -> AgentRunResult:
    """Execute the agent.

    Args:
        user_prompt: The prompt to execute
        model_settings: Model settings (max_tokens, temperature, etc.)
        deps: Dependencies/context for the agent
        **kwargs: Additional arguments

    Returns:
        Agent run result
    """
```

## Best Practices

1. **Always pass model_settings** - Include model settings in all agent calls
2. **Use runtime-specific configs** - Different agents can have different settings
3. **Set appropriate token limits** - Choose based on expected response length
4. **Monitor token usage** - Check logs for actual consumption
5. **Use structured outputs** - Define Pydantic models for result types
6. **Cache prompts** - Use `get_prompt()` for repeated prompts
7. **Test with different settings** - Find optimal temperature and token limits

## Related Documentation

- [Pydantic AI Documentation](https://ai.pydantic.dev/)
- [Configuration Guide](../guides/configuration.md)
- [Runtime Configuration](../guides/runtime-config.md)
- [API Reference](./api.md)
