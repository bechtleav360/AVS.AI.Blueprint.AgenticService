---
description: Create a new AgentRuntime backed by a pydantic-ai LLM agent
---

Ask the user for:
- Agent name / runtime name (e.g. `invoice_agent`)
- Result type / output model name (e.g. `InvoiceOutput`)
- LLM provider (`openai` or `vllm`)
- Model name (e.g. `gpt-4o`)

Then follow these steps:

1. Create the result model in `src/models/schemas.py`:

```python
from pydantic import BaseModel, Field

class {Name}Output(BaseModel):
    """Structured output from the {name} agent."""
    # Add fields based on what the agent should extract/produce
    result: str = Field(description="Primary result")
```

2. Create the system prompt file `src/prompts/system.prompt`:

```
You are a {description} assistant.
{Instructions for the LLM}
Return only structured data — do not add commentary.
```

3. Add agent configuration to `settings.toml`:

```toml
[default.runtimes.{name}]
model_provider    = "{provider}"
model_name        = "{model}"
model_api_key     = "@format {{env[OPENAI_API_KEY]}}"
model_max_tokens  = 2048
model_temperature = 0.1

[default.runtimes.{name}.prompts]
system_prompt_name = "system"
```

4. Build the agent in `src/main.py`:

```python
from pathlib import Path
from blueprint.agents.agent import AgentBuilder
from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.config import Config
from .models import {Name}Output

project_root = Path(__file__).parent.parent
config = Config(settings_files=[project_root / "settings.toml"], root_path=project_root)

{name}_agent = (
    AgentBuilder(config, runtime_name="{name}")
    .with_model_from_config()
    .with_system_prompt_from_config()
    .with_result_type({Name}Output)
    .build()
)

app = (
    AppBuilder(config=config)
    .with_agent({name}_agent)
    .build()
)
```

5. Use the agent in a handler or REST API:

```python
# In on_startup()
self._agent = self.get_registry().get_agent("{name}")

# Running the agent
result = await self._agent.run(input_text)
output: {Name}Output = result.output
```

## Rules to follow

- Use `AgentBuilder` — never instantiate `AgentRuntime` directly.
- The `runtime_name` must match the key in `settings.toml` under `runtimes.*`.
- Place prompt files in `src/prompts/` — they are discovered automatically.
- Store API keys in `secrets.toml` (gitignored), never in `settings.toml`.
- Register the agent with `AppBuilder.with_agent()` before any handlers or APIs that use it.
- See `docs/windsurf/rules/agent-runtime.md` for the full reference.
