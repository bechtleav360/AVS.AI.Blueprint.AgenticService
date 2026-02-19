# Business Service

`BusinessService` is the base class for domain logic components. Services are
the primary way to share state and behaviour between handlers, REST APIs,
schedulers, and agents.

## Defining a service

```python
from blueprint.agents.base import BusinessService
from .models import Invoice


class InvoiceService(BusinessService):
    def __init__(self) -> None:
        super().__init__("invoice_service")   # name is the registry key
        self._invoices: dict[str, Invoice] = {}

    async def on_startup(self) -> None:
        # Optional: connect to DB, load config, etc.
        db_url = self.get_config().get("database_url")
        # await self._connect(db_url)

    async def on_shutdown(self) -> None:
        # Optional: close connections
        pass

    async def save(self, invoice: Invoice) -> Invoice:
        self._invoices[invoice.id] = invoice
        return invoice

    async def get(self, invoice_id: str) -> Invoice | None:
        return self._invoices.get(invoice_id)

    async def list_all(self) -> list[Invoice]:
        return list(self._invoices.values())
```

## Naming

The name passed to `super().__init__()` is the key used when retrieving the
service from the registry:

```python
# Registration
AppBuilder(config).with_service(InvoiceService()).build()

# Retrieval (by name)
service = self.get_registry().get_service("invoice_service")

# Retrieval (by type — preferred, gives correct type hint)
service: InvoiceService = self.get_registry().get_service(InvoiceService)
```

## Accessing config

```python
async def on_startup(self) -> None:
    self._timeout = self.get_config().get("http_timeout", 30)
```

## Accessing other services

Services can depend on other services — resolve them in `on_startup()`:

```python
class ReportService(BusinessService):
    def __init__(self) -> None:
        super().__init__("report_service")

    async def on_startup(self) -> None:
        self._invoices: InvoiceService = self.get_registry().get_service("invoice_service")
```

Register the dependency **before** the dependent service in `AppBuilder`:

```python
app = (
    AppBuilder(config=config)
    .with_service(InvoiceService())   # dependency first
    .with_service(ReportService())    # then the dependent
    .build()
)
```

## Testing

Services are plain Python classes — test them without any framework wiring:

```python
class TestInvoiceService:
    def setup_method(self) -> None:
        self.service = InvoiceService()

    @pytest.mark.asyncio
    async def test_save_and_retrieve(self) -> None:
        invoice = Invoice(id="inv-1", amount=100.0)
        saved = await self.service.save(invoice)
        retrieved = await self.service.get("inv-1")
        assert retrieved == saved
```
