# Agents

Agents provide LLM-powered execution within Blueprint Agents, built on top of Pydantic AI. The `AgentBuilder` fluent API configures an agent, and `AgentRuntime` manages its execution lifecycle.

## Imports

```python
from blueprint.agents import AgentBuilder, AgentRuntime, Config
```

## Purpose

Agents wrap LLM interactions with structured inputs, outputs, tools, and prompt management. They are configured declaratively through the builder pattern and registered with the application so that services and handlers can invoke them by name.

## AgentBuilder Fluent API

Build an agent using the chainable builder methods:

```python
from pydantic import BaseModel
from blueprint.agents import AgentBuilder, Config
from blueprint.agents.agent.tool import Tool


class SummaryOutput(BaseModel):
    title: str
    summary: str
    key_points: list[str]


def search_documents(query: str) -> list[str]:
    """Search the document store for relevant passages."""
    # Tool implementation
    return ["passage 1", "passage 2"]


config = Config()

agent = (
    AgentBuilder(config, runtime_name="summarizer")
    .with_model_from_config()
    .with_system_prompt("summarizer")
    .with_tools([Tool(name="search_documents", function=search_documents)])
    .with_result_type(SummaryOutput)
    .build()
)
```

## Builder Methods

### with_model_from_config()

Loads the model provider, name, and settings from `settings.toml` based on the `runtime_name`. This is the recommended way to configure the model.

```python
.with_model_from_config()
```

### with_system_prompt(name)

Loads a system prompt from `src/prompts/{name}.prompt`. The file should contain the full system prompt text.

```python
.with_system_prompt("summarizer")
# Loads from src/prompts/summarizer.prompt
```

### with_tools(tools)

Registers a list of tools that the LLM can call during execution.

```python
.with_tools([
    Tool(name="search", function=search_func),
    Tool(name="calculate", function=calc_func),
])
```

### with_tool(name, func)

Registers a single tool.

```python
.with_tool("search", search_func)
```

### with_result_type(Model)

Specifies a Pydantic model for structured output. The LLM will be instructed to return data conforming to this schema.

```python
.with_result_type(SummaryOutput)
```

### with_deps_type(Type)

Declares a dependency type that will be injected into tool functions at runtime.

```python
.with_deps_type(MyDependencies)
```

### with_metrics(enabled)

Enables or disables metric collection for this agent.

```python
.with_metrics(True)
```

### build()

Finalizes the agent configuration and returns an `AgentRuntime` instance. The agent is automatically registered with the application registry under its `runtime_name`.

```python
agent = builder.build()
```

## Running an Agent

Once built, invoke the agent with a user prompt:

```python
result = await agent.run("Summarize the Q4 earnings report")
```

The `result` object contains:

- `result.output` -- the structured output (if `with_result_type` was used) or raw text
- Additional metadata about the run

## Structured Output

Use `with_result_type` to get typed, validated responses:

```python
from pydantic import BaseModel


class SentimentResult(BaseModel):
    sentiment: str  # "positive", "negative", "neutral"
    confidence: float
    reasoning: str


agent = (
    AgentBuilder(config, runtime_name="sentiment_analyzer")
    .with_model_from_config()
    .with_system_prompt("sentiment")
    .with_result_type(SentimentResult)
    .build()
)

result = await agent.run("The product exceeded all expectations.")
print(result.output.sentiment)    # "positive"
print(result.output.confidence)   # 0.95
```

## Tool Functions

Tools are plain Python functions that the LLM can invoke during reasoning. They should have clear docstrings, as the LLM uses these to decide when and how to call them.

```python
def get_customer_info(customer_id: str) -> dict:
    """Retrieve customer information by their unique ID.

    Args:
        customer_id: The customer's unique identifier (e.g., "CUST-001").

    Returns:
        A dictionary containing customer name, email, and account status.
    """
    # Implementation here
    return {"name": "Jane Doe", "email": "jane@example.com", "status": "active"}


def calculate_discount(subtotal: float, tier: str) -> float:
    """Calculate the discount amount based on the customer's loyalty tier.

    Args:
        subtotal: The order subtotal in dollars.
        tier: The customer's loyalty tier ("bronze", "silver", "gold", "platinum").

    Returns:
        The discount amount in dollars.
    """
    rates = {"bronze": 0.05, "silver": 0.10, "gold": 0.15, "platinum": 0.20}
    return round(subtotal * rates.get(tier, 0.0), 2)
```

## Prompt Management

Prompts are loaded from prompt files in `src/prompts/`. This keeps prompt text version-controlled and editable without code changes.

```
src/
  prompts/
    system.prompt          # Static system context — no dynamic inputs
    instruction.prompt     # User-facing template — contains {placeholders}
```

Two prompt types serve different purposes:

- **System prompt** (`system.prompt`): Loaded once by `AgentBuilder.with_system_prompt()`. Static context that does not vary per request.
- **Instruction prompt** (`instruction.prompt`): Loaded at call time via `agent.get_prompt()`. Contains `{placeholders}` for dynamic values.

### Injecting Dynamic Values

Use `agent.get_prompt(name).format(**kwargs)` to build the user prompt with runtime values:

```python
prompt = self._agent.get_prompt("instruction").format(
    ticket_text=ticket_text,
    customer_tier=customer_tier,
)
result = await self._agent.run(user_prompt=prompt)
```

Example `src/prompts/instruction.prompt`:

```
Classify the following support ticket:

{ticket_text}

Customer tier: {customer_tier}

Return the category, confidence score, and relevant subcategories.
```

`get_prompt()` caches the file contents after the first load, so repeated calls within the same process incur no I/O overhead.

## Configuration

### settings.toml

Configure each agent runtime in the `[default.runtimes]` section:

```toml
[default.runtimes.summarizer]
model_provider = "openai"       # "openai" or "vllm"
model_name = "gpt-4o-mini"
model_max_tokens = 1000
model_temperature = 0.3

[default.runtimes.sentiment_analyzer]
model_provider = "openai"
model_name = "gpt-4o"
model_max_tokens = 500
model_temperature = 0.0
```

### secrets.toml

Store API keys in `secrets.toml` (never commit this file):

```toml
[default.runtimes.summarizer]
model_api_key = "sk-..."

[default.runtimes.sentiment_analyzer]
model_api_key = "sk-..."
```

Model settings (`max_tokens`, `temperature`) are automatically applied to every agent invocation based on the configuration.

## Metrics

Record execution metrics after a run:

```python
import time

start = time.monotonic()
result = await agent.run("Analyze this document")
duration_ms = (time.monotonic() - start) * 1000

agent.record_metrics(result, duration_ms)
```

This captures token usage, latency, and success/failure status for observability.

## Registration

Register agents with the application builder:

```python
from blueprint.agents import AppBuilder, Config

config = Config()

summarizer = (
    AgentBuilder(config, runtime_name="summarizer")
    .with_model_from_config()
    .with_system_prompt("summarizer")
    .with_result_type(SummaryOutput)
    .build()
)

app = (
    AppBuilder(config)
    .with_agent(summarizer)
    .with_service(DocumentService)
    .with_handler(DocumentHandler)
    .build()
)
```

## Full Example

A complete example showing a handler that uses an agent through a service.

### Agent Setup

```python
from pydantic import BaseModel
from blueprint.agents import AgentBuilder, Config
from blueprint.agents.agent.tool import Tool


class ClassificationResult(BaseModel):
    category: str
    confidence: float
    subcategories: list[str]


def lookup_category_definitions() -> list[dict]:
    """Retrieve the current list of valid categories and their definitions."""
    return [
        {"name": "billing", "description": "Payment and invoice issues"},
        {"name": "technical", "description": "Product bugs and technical problems"},
        {"name": "general", "description": "General inquiries and feedback"},
    ]


config = Config()

classifier_agent = (
    AgentBuilder(config, runtime_name="ticket_classifier")
    .with_model_from_config()
    .with_system_prompt("ticket_classifier")
    .with_tools([Tool(name="lookup_category_definitions", function=lookup_category_definitions)])
    .with_result_type(ClassificationResult)
    .with_metrics(True)
    .build()
)
```

### Service

The recommended pattern for building user prompts with variable inputs is to load an instruction prompt file and use Python's `.format()` to inject dynamic values. This keeps prompt text version-controlled and separate from code.

```python
import time
from blueprint.agents.services.service_base import ServiceBase


class TicketService(ServiceBase):

    def __init__(self) -> None:
        super().__init__()
        self._classifier = None

    async def on_startup(self) -> None:
        self._classifier = self.registry.get_component("ticket_classifier")

    async def classify_ticket(self, ticket_text: str) -> dict:
        if self._classifier:
            # Load the instruction prompt from src/prompts/instruction.prompt
            # and inject dynamic values using .format()
            prompt = self._classifier.get_prompt("instruction").format(
                ticket_text=ticket_text,
            )

            start = time.monotonic()
            result = await self._classifier.run(user_prompt=prompt)
            duration_ms = (time.monotonic() - start) * 1000
            self._classifier.record_metrics(result, duration_ms)

            return {
                "category": result.output.category,
                "confidence": result.data.confidence,
                "subcategories": result.data.subcategories,
            }
```

### Handler

```python
from typing import Any
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.handler.handler_result import HandlerResult
from blueprint.agents.events.generic_cloud_event import GenericCloudEvent


class TicketClassificationHandler(EventHandlerBase):

    def __init__(self) -> None:
        super().__init__(priority=100)
        self._ticket_service = None

    async def on_startup(self) -> None:
        self._ticket_service = self.registry.get_service(TicketService)

    async def can_handle_event(
        self, event: GenericCloudEvent, context: dict[str, Any]
    ) -> bool:
        return event.type == "com.example.ticket.created"

    async def handle_event(
        self, event: GenericCloudEvent, context: dict[str, Any]
    ) -> HandlerResult:
        if self._ticket_service:

            classification = await self._ticket_service.classify_ticket(
                event.data["text"]
            )
            return HandlerResult(
                data={**event.data, "classification": classification},
                event_type="com.example.ticket.classified",
            )
```

### Application Assembly

```python
from blueprint.agents import AppBuilder, Config

config = Config()

app = (
    AppBuilder(config)
    .with_agent(classifier_agent)
    .with_service(TicketService)
    .with_handler(TicketClassificationHandler)
    .build()
)
```

## Testing

Mock the agent runtime to test services and handlers independently of the LLM.

```python
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_classifier():
    classifier = AsyncMock()
    result = MagicMock()
    result.data = MagicMock()
    result.data.category = "billing"
    result.data.confidence = 0.92
    result.data.subcategories = ["invoice", "payment"]
    classifier.run.return_value = result
    classifier.record_metrics = MagicMock()
    return classifier


@pytest.fixture
async def ticket_service(mock_classifier):
    mock_registry = MagicMock()
    mock_registry.get_agent.return_value = mock_classifier

    service = TicketService()
    service.registry = mock_registry
    await service.on_startup()
    return service


@pytest.mark.asyncio
async def test_classify_ticket(ticket_service, mock_classifier):
    result = await ticket_service.classify_ticket("I was charged twice for my order")

    assert result["category"] == "billing"
    assert result["confidence"] == 0.92
    mock_classifier.run.assert_called_once()
    mock_classifier.record_metrics.assert_called_once()


@pytest.mark.asyncio
async def test_handler_delegates_to_service(mock_classifier):
    mock_service = AsyncMock()
    mock_service.classify_ticket.return_value = {
        "category": "technical",
        "confidence": 0.88,
        "subcategories": ["bug"],
    }

    mock_registry = MagicMock()
    mock_registry.get_service.return_value = mock_service

    handler = TicketClassificationHandler()
    handler.registry = mock_registry
    await handler.on_startup()

    event = MagicMock()
    event.type = "com.example.ticket.created"
    event.data = {"ticket_id": "T-1", "text": "App crashes on login"}

    assert await handler.can_handle_event(event, {}) is True
    result = await handler.handle_event(event, {})

    assert result.event_type == "com.example.ticket.classified"
    assert result.data["classification"]["category"] == "technical"
```
