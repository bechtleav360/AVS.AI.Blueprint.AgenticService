# Bechtle Index of Sovereignty Agent Blueprint

**A Python framework for building production-ready AI agents**

## Purpose

The Agent Blueprint framework helps you build intelligent, event-driven microservices powered by AI. It's designed for teams who need to:

- **Process events at scale** - Handle CloudEvents from message brokers (RabbitMQ, Kafka, Azure Service Bus)
- **Integrate AI seamlessly** - Build LLM-powered agents with structured outputs and tool calling
- **Deploy with confidence** - Production-ready patterns with observability, testing, and containerization
- **Maintain code quality** - Enforce best practices through component-based architecture

## Why Use This Framework?

### Built for Production
Stop reinventing the wheel. Get event processing, AI integration, observability, and deployment patterns out of the box.

### Component-Based Architecture
Clear separation of concerns with five base components: BusinessService, EventHandler, RestApi, AgentRuntime, and Scheduler.

### AI-First Design
Native integration with Pydantic AI for structured outputs, tool calling, and multi-model support (OpenAI, vLLM, Anthropic).

### Developer Experience
CLI tools for scaffolding, Windsurf IDE integration, comprehensive testing patterns, and extensive documentation.

## Quick Start

### Install and Create Your First Agent

```bash
# Install the framework
pip install avs-blueprint-agents

# Create a new project
asbs setup my-agent

# Start building
cd my-agent
pip install -e .
asbs dev
```

**Next:** Follow the [Getting Started Guide](docs/guides/getting-started.md) for a complete walkthrough.

## Documentation

### 🚀 Getting Started

- **[Getting Started Guide](docs/guides/getting-started.md)** - Complete setup in 15 minutes
- **[Agent Generator Guide](docs/guides/agent-generator.md)** - Scaffold new projects with CLI tools
- **[Core Concepts](docs/guides/core-concepts.md)** - Understand the framework patterns
- **[Architecture Overview](docs/guides/architecture.md)** - See how components fit together

### 🔨 Building Your Agent

- **[Creating Handlers](docs/guides/handlers.md)** - Process events with chain-of-responsibility
- **[Building LLM Agents](docs/guides/llm-agents.md)** - Integrate AI models with structured outputs
- **[Using Services](docs/guides/services.md)** - Implement business logic and state management
- **[REST APIs](docs/guides/rest-apis.md)** - Expose HTTP endpoints with FastAPI
- **[Background Tasks](docs/guides/schedulers.md)** - Run scheduled jobs with cron

### 📚 Operations & Reference

- **[Testing Guide](docs/guides/testing.md)** - Write unit and integration tests
- **[Deployment Guide](docs/guides/deployment.md)** - Deploy to Kubernetes with Helm
- **[Configuration](docs/guides/configuration.md)** - Manage settings and secrets
- **[Observability](docs/guides/observability.md)** - Tracing, logging, and metrics
- **[Troubleshooting](docs/guides/troubleshooting.md)** - Fix common issues
- **[API Reference](docs/reference/api.md)** - Complete API documentation
- **[Full Documentation Index](docs/README.md)** - Browse all documentation

## Examples

Explore complete example applications in the `examples/` directory:

- **[Invoice Analyzer](examples/invoice_analyzer/)** - Extract structured data from invoices using LLMs
- **[Customer Support QA](examples/customer_support_qa/)** - Answer customer questions with RAG
- **[REST Microservice](examples/rest_microservice/)** - Build HTTP APIs with FastAPI integration

## Requirements

- Python 3.13+
- Docker & Docker Compose (for local development)
- Dapr CLI (for event processing)
- API keys for AI providers (OpenAI, Anthropic, or vLLM endpoint)

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
