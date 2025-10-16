# Custom Agent Implementation

This directory contains your custom agent implementation built on the Agent Blueprint framework.

## Quick Start

```bash
# 1. Copy example files
cp main_example.py main.py

# 2. Implement your agent
# Edit: agent/runtime.py, handlers/*.py

# 3. Configure settings
# Edit: ../dapr/components/*.yaml, settings.yaml

# 4. Run locally
dapr run --app-id your-agent --app-port 8000 -- python main.py
```

## Structure

```
custom/src/
├── agent/          # Your agent implementation
│   ├── runtime.py  # Agent runtime (extends BaseAgent)
│   └── handlers/   # Event handlers
├── api/            # Custom API endpoints (optional)
├── handlers/       # Additional handlers (optional)
└── main.py         # Application entry point
```

## Documentation

For detailed guides, see:

- **[Architecture Guide](../../docs/guides/architecture.md)** - System architecture and patterns
- **[Getting Started](../../docs/guides/getting-started.md)** - Step-by-step implementation guide
- **[Configuration Guide](../../docs/guides/configuration/)** - Settings and environment variables
- **[Handler Development](../../docs/guides/handler-development.md)** - Creating event handlers
- **[Agent Development](../../docs/guides/agent-development.md)** - Building AI agents
- **[API Reference](../../docs/reference/api.md)** - Complete API documentation

## Key Concepts

**Framework (base/)** - Reusable components, do not modify
**Custom (custom/)** - Your implementation, customize freely

Import from base framework:
```python
from base.src.config import Config
from base.src.agent import BaseAgent
from base.src.handler import EventHandler
```

## Examples

See working examples in:
- `main_example.py` - Simple single-runtime agent
- `main_multi_runtime_example.py` - Multi-runtime agent
- `handlers/` - Example event handlers
