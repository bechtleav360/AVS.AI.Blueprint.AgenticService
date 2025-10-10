# Design Patterns

Design patterns used in the Agent Blueprint framework.

## 1. Chain of Responsibility

**Purpose:** Process events through a chain of handlers

**Implementation:**
```python
class EventHandler(ABC):
    def __init__(self, name: str, priority: int):
        self.name = name
        self.priority = priority
    
    async def can_handle(self, event, context) -> bool:
        pass
    
    async def handle(self, event, context):
        pass
```

**Usage:**
- Handlers are sorted by priority
- Each handler can process or pass to next
- First handler to return non-None stops chain

**Benefits:**
- Flexible event processing
- Easy to add/remove handlers
- Testable in isolation

## 2. Template Method

**Purpose:** Define workflow in base class, details in subclass

**Implementation:**
```python
class EventHandler(ABC):
    async def handle(self, event, context):
        # Framework adds tracing
        with tracer.start_span(f"handler.{self.name}"):
            return await self._handle(event, context)
    
    @abstractmethod
    async def _handle(self, event, context):
        """Subclass implements this"""
        pass
```

**Benefits:**
- Consistent cross-cutting concerns
- Subclasses focus on business logic
- Framework handles infrastructure

## 3. Builder Pattern

**Purpose:** Fluent interface for configuration

**Implementation:**
```python
class AppBuilder:
    def with_handler(self, handler_class):
        self._handlers.append(handler_class)
        return self
    
    def with_agent_runtime(self, runtime_class):
        self._runtimes.append(runtime_class)
        return self
    
    def build(self):
        return self._create_app()
```

**Usage:**
```python
app = (
    AppBuilder()
    .with_handler(Handler1)
    .with_handler(Handler2)
    .with_agent_runtime(MyAgent)
    .build()
)
```

**Benefits:**
- Readable configuration
- Type-safe
- Chainable methods

## 4. Dependency Injection

**Purpose:** Provide dependencies to components

**Implementation:**
```python
class MyHandler(EventHandler):
    def __init__(self, database, cache):
        super().__init__("MyHandler", priority=20)
        self.database = database
        self.cache = cache
```

**Benefits:**
- Testable (inject mocks)
- Flexible (swap implementations)
- Clear dependencies

## 5. Registry Pattern

**Purpose:** Central storage for components

**Implementation:**
```python
class ComponentRegistry:
    def register_handler(self, handler):
        self._handlers.append(handler)
    
    def get_handlers(self):
        return sorted(self._handlers, key=lambda h: h.priority)
```

**Benefits:**
- Single source of truth
- Easy component lookup
- Centralized management

## 6. Strategy Pattern

**Purpose:** Swap algorithms at runtime

**Implementation:**
```python
class BaseAgent(ABC):
    @abstractmethod
    def _get_tools(self) -> list:
        """Different agents provide different tools"""
        pass
```

**Usage:**
```python
class InvoiceAgent(BaseAgent):
    def _get_tools(self):
        return [calculate_invoice]

class AssetAgent(BaseAgent):
    def _get_tools(self):
        return [check_backup]
```

**Benefits:**
- Flexible behavior
- Easy to add new strategies
- Runtime selection

## See Also

- [Architecture Overview](../guides/architecture.md) - How patterns fit together
- [Creating Handlers](../guides/handlers.md) - Chain of Responsibility in practice
- [App Builder Guide](../guides/app-builder.md) - Builder pattern usage
