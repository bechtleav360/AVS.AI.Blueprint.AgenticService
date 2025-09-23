# Agent Blueprint Structure

This agent blueprint is organized to separate framework components from customizable implementation:

## Directory Structure

```
Agents_Blueprint/
├── base/                    # Framework components (DO NOT MODIFY)
│   └── src/
│       ├── agent/          # Base agent runtime and framework
│       ├── api/            # Framework API components (actuators, deps)
│       ├── gateways/       # Data gateway clients
│       ├── models/         # Base domain models
│       ├── app.py          # FastAPI application factory
│       ├── config.py       # Configuration management
│       └── telemetry.py    # Observability and tracing
├── agent/                   # Agent implementation
│   └── src/
│       ├── custom/         # Implementation-specific components (CUSTOMIZE THESE)
│       │   ├── agent/      # Your agent implementation
│       │   ├── api/        # Your custom API routes
│       │   └── prompts/    # Your system prompts
│       └── main.py         # Application entry point
└── docs/                   # Documentation
```

## Base Components (Framework)

These components provide the core framework functionality and should **NOT** be modified when implementing a new agent:

- **`base/config.py`**: Configuration management using Dynaconf
- **`base/telemetry.py`**: OpenTelemetry setup and instrumentation
- **`base/app.py`**: FastAPI application factory with middleware setup
- **`base/agent/base/`**: Abstract base classes for agent runtime
- **`base/api/actuators.py`**: Health check and monitoring endpoints
- **`base/api/deps.py`**: Dependency injection framework
- **`base/gateways/`**: Data gateway client implementations
- **`base/models/`**: Base domain models and event structures

## Custom Components (Implementation)

These components should be customized for your specific agent implementation:

- **`custom/agent/runtime.py`**: Your agent implementation (extends BaseAgent)
- **`custom/agent/tools.py`**: Your agent's tools and functions
- **`custom/agent/handlers.py`**: Your event handlers
- **`custom/agent/logic.py`**: Your business logic
- **`custom/api/rest.py`**: Your RESTful API endpoints
- **`custom/api/events.py`**: Your event-based API endpoints
- **`custom/prompts/`**: Your system prompts and templates

## Getting Started

1. **Implement your agent**: Start by customizing `custom/agent/runtime.py`
2. **Add your tools**: Implement your agent's capabilities in `custom/agent/tools.py`
3. **Create your prompts**: Add your system prompts to `custom/prompts/`
4. **Add your API routes**: Customize `custom/api/rest.py` and `custom/api/events.py`
5. **Implement business logic**: Add your domain logic to `custom/agent/handlers.py`

## Key Principles

- **Separation of Concerns**: Framework code is separate from implementation code
- **Dependency Injection**: Configuration and dependencies are injected, not global
- **Extensibility**: The base framework can be extended without modification
- **Testability**: Clean separation makes unit testing easier
- **Maintainability**: Updates to the framework don't affect your implementation

## Import Guidelines

- Custom components should import from `base.src.*` for framework functionality (absolute imports)
- Base components should not import from `agent.src.custom.*` (except for app.py)
- Use relative imports within the same module (base or custom)
- Use absolute imports when crossing module boundaries

## Example Usage

```python
# In agent/src/custom/agent/runtime.py
from base.src.config import Config
from base.src.agent.base.runtime import BaseAgent

# In agent/src/custom/api/rest.py  
from base.src.config import Config

# In agent/src/main.py
from base.src.app import app
```

This structure ensures that your custom implementation remains separate from the framework, making it easier to maintain and update both components independently.
