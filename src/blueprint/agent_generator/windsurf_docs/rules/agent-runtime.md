# Agent Runtime

`AgentRuntime` wraps a pydantic-ai `Agent` and integrates it into the
Blueprint component lifecycle. It provides automatic model settings injection
(max_tokens, temperature) from configuration.

## Defining an agent runtime

```python
from pydantic_ai import Agent
from blueprint.agents.base import AgentRuntime
from .models import InvoiceOutput


class InvoiceAgent(AgentRuntime):
    """LLM agent for extracting structured data from invoices."""

    def __init__(self, config, runtime_name: str = "invoice_agent") -> None:
        super().__init__(config=config, runtime_name=runtime_name)
```

## Building with AgentBuilder

Use `AgentBuilder` to construct the agent runtime — do not instantiate
`AgentRuntime` subclasses directly:

```python
from blueprint.agents.agent import AgentBuilder
from blueprint.agents.config import Config

config = Config(settings_files=[...], root_path=...)

invoice_agent = (
    AgentBuilder(config, runtime_name="invoice_agent")
    .with_model_from_config()          # reads model_provider, model_name, etc.
    .with_system_prompt_from_config()  # reads system_prompt_name from config
    .with_result_type(InvoiceOutput)
    .build()
)
```

## Configuration keys (settings.toml)

```toml
[default.runtimes.invoice_agent]
model_provider    = "openai"
model_name        = "gpt-4o"
model_api_key     = "@format {env[OPENAI_API_KEY]}"
model_max_tokens  = 2048
model_temperature = 0.1

[default.runtimes.invoice_agent.prompts]
system_prompt_name = "system"   # loads system.prompt from prompts/ directory
```

## Registering with AppBuilder

```python
app = (
    AppBuilder(config=config)
    .with_agent(invoice_agent)
    .with_handler(InvoiceHandler())
    .build()
)
```

## Running the agent inside a handler

```python
class InvoiceHandler(EventHandler):
    async def on_startup(self) -> None:
        self._agent = self.get_registry().get_agent("invoice_agent")

    async def handle_event(self, event, context) -> HandlerResult | None:
        result = await self._agent.run(event.data["text"])
        return HandlerResult(
            event_type="invoice.extracted",
            data=result.output.model_dump(),
        )
```

## Running the agent inside a REST API

```python
class InvoiceApi(RestApi):
    async def on_startup(self) -> None:
        self._agent = self.get_registry().get_agent("invoice_agent")

    @RestApi.post("/invoices/extract", response_model=InvoiceOutput)
    async def extract(self, payload: InvoiceRequest) -> InvoiceOutput:
        result = await self._agent.run(payload.text)
        return result.output
```

## Model settings

Model settings (max_tokens, temperature) are read from config and applied
automatically on every `agent.run()` call. Override per-call if needed:

```python
result = await self._agent.run(
    prompt,
    model_settings={"max_tokens": 512, "temperature": 0.0},
)
```

## Prompt files

Place prompt files in a `prompts/` directory next to your source:

```
src/
└── prompts/
    └── system.prompt    # loaded when system_prompt_name = "system"
```

Prompt files are plain text. Use `{variable}` for dynamic substitution if
needed via `with_prompt()`.
