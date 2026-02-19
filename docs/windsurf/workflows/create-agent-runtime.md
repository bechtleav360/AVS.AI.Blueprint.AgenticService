---
description: Create a new AgentRuntime backed by a pydantic-ai LLM agent
---

## Steps

1. Identify the agent name (e.g. `invoice_agent`), result type, and target directory.

2. Create the result model in `src/models/schemas.py`:

```python
from pydantic import BaseModel, Field

class InvoiceOutput(BaseModel):
    vendor: str = Field(description="Vendor name")
    total: float = Field(description="Total amount")
    currency: str = Field(description="Currency code")
    date: str = Field(description="Invoice date (ISO 8601)")
```

3. Create the system prompt file `src/prompts/system.prompt`:

```
You are an invoice extraction assistant.
Extract structured data from the provided invoice text.
Return only the fields requested — do not add commentary.
```

4. Add agent configuration to `settings.toml`:

```toml
[default.runtimes.invoice_agent]
model_provider    = "openai"
model_name        = "gpt-4o"
model_api_key     = "@format {env[OPENAI_API_KEY]}"
model_max_tokens  = 1024
model_temperature = 0.0

[default.runtimes.invoice_agent.prompts]
system_prompt_name = "system"
```

5. Build the agent in `src/main.py`:

```python
from pathlib import Path
from blueprint.agents.agent import AgentBuilder
from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.config import Config
from .models import InvoiceOutput

project_root = Path(__file__).parent.parent
config = Config(settings_files=[project_root / "settings.toml"], root_path=project_root)

invoice_agent = (
    AgentBuilder(config, runtime_name="invoice_agent")
    .with_model_from_config()
    .with_system_prompt_from_config()
    .with_result_type(InvoiceOutput)
    .build()
)

app = (
    AppBuilder(config=config)
    .with_agent(invoice_agent)
    .with_handler(InvoiceHandler())
    .build()
)
```

6. Use the agent inside a handler or REST API:

```python
# In a handler
async def on_startup(self) -> None:
    self._agent = self.get_registry().get_agent("invoice_agent")

async def handle_event(self, event, context):
    result = await self._agent.run(event.data["text"])
    return HandlerResult(event_type="invoice.extracted", data=result.output.model_dump())

# In a REST API
async def on_startup(self) -> None:
    self._agent = self.get_registry().get_agent("invoice_agent")

@RestApi.post("/invoices/extract", response_model=InvoiceOutput)
async def extract(self, payload: InvoiceRequest) -> InvoiceOutput:
    result = await self._agent.run(payload.text)
    return result.output
```

## Rules

- Use `AgentBuilder` — never instantiate `AgentRuntime` directly.
- The `runtime_name` in `AgentBuilder(config, runtime_name=...)` must match the key in `settings.toml` under `runtimes.*`.
- Place prompt files in `src/prompts/` — they are discovered automatically.
- Store the API key in `secrets.toml` or as an environment variable, never in `settings.toml`.
- Register the agent with `AppBuilder.with_agent()` before any handlers or APIs that use it.
