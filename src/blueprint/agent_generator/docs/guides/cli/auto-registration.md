# Auto-Registration Troubleshooting

When `asbs create` commands run, they attempt to automatically register components in `src/main.py`. If this fails, the CLI provides clear guidance on manual registration.

## Common Issues

### `src/main.py` Not Found

**Error:**
```
⚠ Could not auto-register (src/main.py not found or invalid)
```

**Solution:**
Ensure your project has the correct structure:
```
my_service/
├── src/
│   └── main.py
└── pyproject.toml
```

Run `asbs setup <project-name>` to scaffold a complete project if needed.

### Invalid main.py Structure

**Error:**
```
⚠ Could not auto-register (src/main.py not found or invalid)
```

**Solution:**
Verify `src/main.py` contains:
- Import statements at the top
- An assignment whose right-hand side opens a parenthesis, with `AppBuilder(` on the next line
- A closing `)` in the first column -- or, in a project that still builds its own application, a
  `.build()` call

That is what the CLI looks for when it rewrites the chain: it is a line-oriented editor for a file
the generator wrote in a known shape, not a parser, and it reports a file it cannot read rather
than guessing at one.

Example valid structure:
```python
from blueprint.agents.app_builder import AppBuilder

agent = (
    AppBuilder()
    # Components added here
)
```

## Manual Registration

If auto-registration fails, the CLI displays instructions. Follow this pattern for each component type:

Every registration is the **class**, not an instance of it, and the declaration ends without a
`build()` call -- the host builds it.

### Handler
```python
# In src/main.py

from .handlers import OrderPlacedHandler

agent = (
    AppBuilder()
    .with_handler(OrderPlacedHandler)
)
```

### Service
```python
# In src/main.py

from .services import InvoiceProcessorService

agent = (
    AppBuilder()
    .with_service(InvoiceProcessorService)
)
```

### API
```python
# In src/main.py

from .api import OrderManagementApi

agent = (
    AppBuilder()
    .with_rest_api(OrderManagementApi)
)
```

### Agent
```python
# In src/main.py

from blueprint.agents.agent import AgentBuilder

document_analyzer_agent = (
    AgentBuilder(runtime_name="document_analyzer_agent")
    .with_model_from_config()
    .with_system_prompt("document_analyzer_agent_system")
)

agent = (
    AppBuilder()
    .with_agent(document_analyzer_agent, name="document_analyzer_agent")
)
```

The `AgentBuilder` is left **unbuilt**. `AppBuilder.build()` calls
`agent.build(config.for_namespace(<this agent>))`, so the model, prompt and metrics come from this
agent's own configuration view; building it here would bind it to whatever configuration happened
to be in scope at that line, which in a group is a neighbour's. The `name=` is the registry key
services resolve the runtime by.

### Scheduler
```python
# In src/main.py

from .schedulers import CleanupScheduler

agent = (
    AppBuilder()
    .with_scheduler(CleanupScheduler)
)
```

## Registration Order Matters

Register dependencies **before** dependents in the AppBuilder chain:

1. Services first (contain business logic)
2. Handlers and APIs next (use services)
3. Agents last (may use multiple services)
4. Schedulers last (use services)

```python
agent = (
    AppBuilder()
    # 1. Services
    .with_service(OrderService)
    .with_service(PaymentService)
    # 2. Handlers and APIs
    .with_handler(OrderPlacedHandler)
    .with_rest_api(OrderApi)
    # 3. Agents
    .with_agent(analyzer_agent, name="analyzer_agent")
    # 4. Schedulers
    .with_scheduler(CleanupScheduler)
)
```
