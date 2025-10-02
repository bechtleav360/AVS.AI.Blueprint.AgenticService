# Pydantic AI Trial

Simple example showing how to create a Pydantic AI agent with tools.

## What's Here

**`pydantic_ai_trial.py`** - Minimal Pydantic AI agent example
- Simple models (Resource, Analysis)
- One tool (check_resource)
- Agent that uses the tool
- Two test cases

## Quick Start

```bash
# Install dependencies
pip install pydantic-ai openai

# Set API credentials
export OPENAI_API_KEY="your-key"

# Optional: Use custom endpoint (e.g., vLLM)
export OPENAI_BASE_URL="https://your-endpoint/v1"

# Run the trial
python pydantic_ai_trial.py
```

## How It Works

1. **Define models** - What goes in and what comes out
2. **Create a tool** - Function that does the actual work
3. **Create agent** - Configure model and register tools
4. **Run agent** - Pass data and get results

## Customize It

Replace the example logic with your own:

```python
# Your models
class YourInput(BaseModel):
    # your fields

class YourOutput(BaseModel):
    # your fields

# Your tool
async def your_tool(ctx: RunContext[None], input: YourInput) -> YourOutput:
    # your logic
    return YourOutput(...)

# Your agent (modern approach)
agent = Agent(
    'openai:gpt-4o',  # Model string
    result_type=YourOutput,
    system_prompt="Your instructions",
)
agent.tool(your_tool)
```

## Next Steps

Once your agent works here, migrate it to the blueprint:
1. Move models to `custom/src/models/`
2. Move logic to `custom/src/agent/logic.py`
3. Move tools to `custom/src/agent/tools.py`
4. Update `custom/src/agent/runtime.py`
