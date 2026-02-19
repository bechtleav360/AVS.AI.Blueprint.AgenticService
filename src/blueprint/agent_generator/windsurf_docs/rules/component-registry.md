# Component Registry

The `ComponentRegistry` is the central hub that connects all components at
runtime. It is created and owned by `AppBuilder` — you never instantiate it
directly.

## Accessing the registry

Every `Component` subclass has `self.get_registry()` available **after**
`AppBuilder` has wired it (i.e. inside `on_startup()` and any method called
after startup):

```python
registry = self.get_registry()
```

Calling `get_registry()` in `__init__` raises `RuntimeError` because the
registry is not linked until `AppBuilder.build()` runs.

## Retrieving components

### BusinessService

```python
# By name (returns BusinessService — cast if needed)
service = self.get_registry().get_service("invoice_service")

# By type (returns correctly typed instance)
service: InvoiceService = self.get_registry().get_service(InvoiceService)
```

### AgentRuntime

```python
agent = self.get_registry().get_agent("invoice_agent")
agent: InvoiceAgent = self.get_registry().get_agent(InvoiceAgent)
```

### RestApi

```python
api = self.get_registry().get_rest_api("invoice_api")
api: InvoiceApi = self.get_registry().get_rest_api(InvoiceApi)
```

### Schedulers

Schedulers are not individually retrievable by name — they are managed
collectively by `AppBuilder`. Use a shared `BusinessService` to communicate
between a scheduler and other components.

## Registration

Components are registered via `AppBuilder` — **never** call
`registry.register_*()` directly in application code:

```python
# Correct
app = AppBuilder(config).with_service(InvoiceService()).build()

# Wrong — bypasses lifecycle wiring
registry.register_service(InvoiceService())
```

## Checking existence

```python
if self.get_registry().has_service("cache_service"):
    cache = self.get_registry().get_service("cache_service")
```

Available: `has_service()`, `has_agent()`, `has_rest_api()`, `has_handler()`,
`has_cache()`.

## Listing registered components

```python
service_list  = self.get_registry().list_services()   # list[BusinessService]
agent_names   = self.get_registry().list_agents()     # list[str]
api_names     = self.get_registry().list_rest_apis()  # list[str]
handlers      = self.get_registry().get_handlers()    # list[EventHandler] sorted by priority
```

## Cache service

The optional built-in cache is registered separately:

```python
# AppBuilder wires this automatically when with_cache() is called
cache = self.get_registry().get_cache()   # raises ValueError if not registered
```

## Settings

```python
settings = self.get_registry().get_settings()   # returns Config instance
```

Prefer `self.get_config()` (inherited from `Component`) over this.

## Common mistakes

| Mistake | Fix |
|---------|-----|
| `get_registry()` in `__init__` | Move to `on_startup()` |
| Storing a reference to the registry in a module-level variable | Always access via `self.get_registry()` |
| Registering the same name twice | Each component name must be unique per type |
| Calling `get_service()` with a name that was never registered | Ensure `with_service()` is called in `main.py` |
