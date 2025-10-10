# Bechtle Index of Sovereignty Agent Blueprint

**A microservice framework for building AI-powered agents**

## What Is This?

The Agent Blueprint helps you build intelligent agents that process events and make decisions using AI. It provides:

- ✅ **Event-driven architecture** with Dapr and RabbitMQ
- ✅ **AI integration** with Pydantic AI (OpenAI, vLLM, etc.)
- ✅ **Chain of Responsibility** pattern for flexible event processing
- ✅ **Built-in observability** with OpenTelemetry tracing
- ✅ **Production-ready** with health checks, testing, and Docker support

## Quick Start

```bash
# Clone and setup
git clone https://dev.azure.com/av360/Bechtle-Index-of-Sovereignty/_git/Agents_Blueprint
cd Agents_Blueprint

# Install dependencies
uv venv .venv --python 3.13
source .venv/bin/activate
uv pip install -e "custom/.[dev]"

# Configure
cp custom/secrets.toml.example custom/secrets.toml
# Edit secrets.toml with your AI API key

# Run
cd custom && uv run uvicorn src.main:app --reload --port 8001
```

**Next:** Follow the [Getting Started Guide](docs/guides/getting-started.md) for detailed instructions.

## Documentation

### 🚀 New to Agent Blueprint?

1. **[Getting Started](docs/guides/getting-started.md)** - Set up in 15 minutes
2. **[Core Concepts](docs/guides/core-concepts.md)** - Understand key patterns
3. **[Architecture Overview](docs/guides/architecture.md)** - See how it all fits together

### 🔨 Building Your Agent

4. **[Setting Up Events](docs/guides/events-setup.md)** - Configure Dapr and RabbitMQ
5. **[Using the App Builder](docs/guides/app-builder.md)** - Initialize your application
6. **[Creating Handlers](docs/guides/handlers.md)** - Build event processors
7. **[Building LLM Agents](docs/guides/llm-agents.md)** - Integrate AI models

### 📚 Reference & Operations

- **[Testing Guide](docs/testing-guide.md)** - Write tests
- **[Deployment Guide](docs/deployment-guide.md)** - Deploy to production
- **[Troubleshooting](docs/troubleshooting.md)** - Fix common issues
- **[Full Documentation Index](docs/README.md)** - All docs

## Key Features

### Event-Driven Processing

Subscribe to events from RabbitMQ, Kafka, or Azure Service Bus:

```python
# Handlers process events in priority order
app = (
    AppBuilder()
    .with_handler(ValidationHandler)      # Priority 10
    .with_handler(EnrichmentHandler)      # Priority 20
    .with_handler(AgentInvokerHandler)    # Priority 30
    .build()
)
```

### AI Integration

Build agents with Pydantic AI:

```python
class InvoiceAgent(BaseAgent):
    def _get_tools(self):
        return [calculate_invoice, lookup_customer]
    
    def _get_result_type(self):
        return InvoiceAnalysisOutput
```

### Built-in Observability

Automatic tracing, logging, and health checks:

```bash
# Health check
curl http://localhost:8001/actuators/health

# OpenTelemetry traces automatically captured
```

## Architecture

```
┌─────────────┐         ┌──────────┐         ┌──────────┐
│  RabbitMQ   │────────▶│ Handlers │────────▶│ AI Agent │
│   Events    │         │  Chain   │         │ (Optional)│
└─────────────┘         └──────────┘         └──────────┘
```

**Key Patterns:**
- **Chain of Responsibility** - Handlers process events in sequence
- **Template Method** - Override specific methods, framework handles the rest
- **Dependency Injection** - Components receive dependencies
- **Observability First** - Tracing and logging built-in

## Project Structure

```
Agents_Blueprint/
├── base/                    # Framework (don't modify)
│   ├── src/
│   │   ├── agent/          # Base agent classes
│   │   ├── api/            # API endpoints
│   │   ├── models/         # Data models
│   │   └── services/       # Processing services
│   └── requirements.txt
│
├── custom/                  # Your agent (modify this!)
│   ├── src/
│   │   ├── agent/
│   │   │   ├── handlers.py # Event handlers
│   │   │   ├── runtime.py  # AI agent runtime
│   │   │   └── tools.py    # AI tools
│   │   ├── api/
│   │   │   └── rest.py     # Custom endpoints
│   │   ├── models/         # Your data models
│   │   └── main.py         # Application entry
│   ├── settings.toml       # Configuration
│   └── secrets.toml        # Secrets (not in git)
│
└── docs/                    # Documentation
    └── guides/             # Step-by-step guides
```

## Requirements

- **Python 3.13+**
- **Docker & Docker Compose** (for local development)
- **Dapr CLI** (for event processing)
- **API Key** for OpenAI or access to vLLM

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Support

- **Documentation:** [docs/README.md](docs/README.md)
- **Troubleshooting:** [docs/guides/troubleshooting.md](docs/guides/troubleshooting.md)
- **Issues:** Open an issue on Azure DevOps

## License

Copyright © 2025 Bechtle AG. All rights reserved.

---

**Ready to build your agent?** Start with the [Getting Started Guide](docs/guides/getting-started.md) →
