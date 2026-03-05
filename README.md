# Agent Blueprint

## Purpose

Agent Blueprint is a Python framework for building event-driven AI agents with a consistent application structure, handler pipeline, and shared infrastructure for configuration, observability, and deployment.

## Documentation

Guides: [Getting Started](docs/guides/getting-started.md), [Core Concepts](docs/guides/core-concepts.md), [Architecture Overview](docs/guides/architecture.md), [Events Setup](docs/guides/events-setup.md), [App Builder](docs/guides/app-builder.md), [Handlers](docs/guides/handlers.md), [LLM Agents](docs/guides/llm-agents.md)

Reference: [Testing Guide](docs/testing-guide.md), [Deployment Guide](docs/deployment-guide.md), [Troubleshooting](docs/guides/troubleshooting.md), [Full Documentation Index](docs/README.md)

## Directory Layout

```
AVS.AI.Blueprint.AgenticService/
├── src/
│   └── blueprint/
│       └── agents/              # Framework package (avs-blueprint-agents)
│           ├── agent/           # Base agent classes
│           ├── api/             # API endpoints
│           ├── config/          # Configuration management
│           ├── models/          # Data models
│           ├── services/        # Processing services
│           └── py.typed         # PEP 561 type hints marker
├── examples/
│   └── complex_agent/        # Example agent service
│       ├── src/                 # App code (api, handlers, models, services)
│       ├── tests/               # Example tests
│       └── pyproject.toml       # Example dependencies
├── tests/                       # Framework tests
├── docs/                        # Documentation
├── pyproject.toml               # Framework package config
├── pytest.ini                   # Test configuration
└── README.md                    # This file
```
