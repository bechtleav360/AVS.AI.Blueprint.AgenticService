# Agent Blueprint Documentation

**Welcome!** This documentation helps you build intelligent agents using the Agent Blueprint framework.

> **For Junior Developers:** This documentation is written with you in mind. We explain concepts clearly, provide examples, and guide you step-by-step.

## 📚 Documentation Structure

### 🚀 Start Here

**New to the Agent Blueprint?** Follow this path:

1. **[Getting Started](guides/getting-started.md)** ⭐ - Set up your environment in 15 minutes
2. **[Architecture Overview](guides/architecture.md)** - Understand how everything fits together
3. **[Core Concepts](guides/core-concepts.md)** - Learn the key patterns

### 🔨 Building Your Agent

Follow these guides to build a complete agent:

1. **[Setting Up Events](guides/events-setup.md)** - Configure Dapr, RabbitMQ, and subscriptions
2. **[Event Routing](guides/event-routing.md)** - Configure topics and routing keys for advanced message routing
3. **[Using the App Builder](guides/app-builder.md)** - Initialize your application
4. **[Creating Handlers](guides/handlers.md)** - Process events with Chain of Responsibility
5. **[Building LLM Agents](guides/llm-agents.md)** - Integrate AI models with Pydantic AI

### ⚙️ Configuration

In-depth configuration guides:

- **[Configuration Overview](guides/configuration/README.md)** - Configuration guide index
- **[Agent Configuration](guides/configuration/agent-configuration.md)** - AI models, application settings
- **[Dynaconf](guides/configuration/dynaconf.md)** - Configuration management system
- **[OpenTelemetry](guides/configuration/opentelemetry.md)** - Distributed tracing and observability
- **[Dapr Configuration](guides/configuration/dapr-configuration.md)** - Pub/Sub, subscriptions, secrets

### 🚢 Deployment & Testing

5. **[Testing Your Agent](guides/testing.md)** - Write unit and integration tests
6. **[Deployment Guide](guides/deployment.md)** - Deploy with Docker and Kubernetes
7. **[Troubleshooting](guides/troubleshooting.md)** - Fix common issues

### 📖 Reference

- **[API Reference](reference/api.md)** - Complete API documentation
- **[Configuration](reference/configuration.md)** - All settings explained
- **[Design Patterns](reference/design-patterns.md)** - Patterns used in the framework

### 📋 Project Info

- **[Changelog](changelog.md)** - Version history
- **[Roadmap](roadmap.md)** - Future plans
- **[Requirements](requirements.md)** - System requirements

## 🎯 Quick Navigation

**I want to...**
- **Get started quickly** → [Getting Started Guide](guides/getting-started.md)
- **Understand the architecture** → [Architecture Overview](guides/architecture.md)
- **Set up event processing** → [Events Setup](guides/events-setup.md)
- **Create a handler** → [Handlers Guide](guides/handlers.md)
- **Add an AI agent** → [LLM Agents Guide](guides/llm-agents.md)
- **Deploy my agent** → [Deployment Guide](guides/deployment.md)
- **Fix an issue** → [Troubleshooting](guides/troubleshooting.md)

## 📖 How to Read This Documentation

**If you're new to development:**
- Read guides in order, starting with Getting Started
- Don't skip the "Why?" sections - they explain the reasoning
- Try the examples as you go
- Ask questions if something isn't clear

**If you're experienced:**
- Skim [Architecture Overview](guides/architecture.md) for the mental model
- Jump to specific guides as needed
- Use [API Reference](reference/api.md) for details

## 💡 Key Concepts

The Agent Blueprint is built on these principles:

- **Separation of Concerns** - Base framework handles infrastructure, you write business logic
- **Chain of Responsibility** - Handlers process events in priority order
- **Template Method Pattern** - Override specific methods, framework handles the rest
- **Observability First** - Tracing, logging, and metrics built-in

## 🤝 Getting Help

- **Documentation unclear?** Open an issue to improve it
- **Found a bug?** Check [Troubleshooting](guides/troubleshooting.md) first
- **Want to contribute?** See [CONTRIBUTING.md](../CONTRIBUTING.md)

---

*Last updated: 2025-10-10 | Maintained by the Agents Blueprint team*
