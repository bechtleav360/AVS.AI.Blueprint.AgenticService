# Event Handler

`EventHandler` implements the Chain of Responsibility pattern for processing
CloudEvents. Handlers are evaluated in priority order; the first handler that
returns a non-`None` result stops the chain.

## Defining a handler

```python
from blueprint.agents.base import EventHandler
from blueprint.agents.models import HandlerResult
from blueprint.agents.models.events import GenericCloudEvent
from .services import InvoiceService


class InvoiceHandler(EventHandler):
    def __init__(self) -> None:
        super().__init__(name="InvoiceHandler", priority=10)

    async def on_startup(self) -> None:
        self._service: InvoiceService = self.get_registry().get_service("invoice_service")
        self._agent = self.get_registry().get_agent("invoice_agent")

    async def can_handle_event(
        self, event: GenericCloudEvent, context: dict
    ) -> bool:
        return event.type == "invoice.received"

    async def handle_event(
        self, event: GenericCloudEvent, context: dict
    ) -> HandlerResult | None:
        result = await self._agent.run(event.data)
        return HandlerResult(
            event_type="invoice.processed",
            data=result.output,
            metadata={"handler": self.get_name()},
        )
```

## Priority

Lower numbers run first. Use priority to control evaluation order:

```python
super().__init__(name="ValidationHandler", priority=10)   # runs first
super().__init__(name="ProcessingHandler", priority=20)   # runs second
super().__init__(name="FallbackHandler",   priority=100)  # runs last
```

## Return values

| Return value | Effect |
|-------------|--------|
| `HandlerResult(event_type=..., data=..., metadata=...)` | Stops chain; result is published as event |
| `HandlerResult(event_type=None, ...)` | Stops chain; result is NOT published |
| `list[HandlerResult]` | Stops chain; each result with non-None `event_type` is published |
| `None` | Passes to next handler |

## Accessing agents

```python
agent = self.get_registry().get_agent("my_agent")
result = await agent.run(prompt, deps=my_deps)
```

## Registering with AppBuilder

```python
app = (
    AppBuilder(config=config)
    .with_service(InvoiceService())
    .with_agent(invoice_agent)
    .with_handler(InvoiceHandler())
    .build()
)
```

## Testing

```python
from unittest.mock import AsyncMock, MagicMock


class TestInvoiceHandler:
    def setup_method(self) -> None:
        self.handler = InvoiceHandler()
        registry = MagicMock()
        registry.get_service.return_value = MagicMock(spec=InvoiceService)
        registry.get_agent.return_value = AsyncMock()
        self.handler._registry = registry

    @pytest.mark.asyncio
    async def test_can_handle_invoice_event(self) -> None:
        event = GenericCloudEvent(type="invoice.received", data={})
        assert await self.handler.can_handle_event(event, {}) is True

    @pytest.mark.asyncio
    async def test_ignores_other_events(self) -> None:
        event = GenericCloudEvent(type="order.placed", data={})
        assert await self.handler.can_handle_event(event, {}) is False
```
