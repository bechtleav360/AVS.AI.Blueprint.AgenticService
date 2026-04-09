# AVS Agent Blueprint

The Agent Blueprint is a Python framework for building event-driven AI agents with a consistent application structure, handler pipeline, and shared infrastructure for configuration, observability, and deployment.

```bash
uv add avs-blueprint-agents
```

Guides: [Getting Started](docs/guides/getting-started.md), [Core Concepts](docs/guides/core-concepts.md), [Architecture Overview](docs/guides/architecture.md), [Events Setup](docs/guides/events-setup.md), [App Builder](docs/guides/app-builder.md), [Handlers](docs/guides/handlers.md), [LLM Agents](docs/guides/llm-agents.md)

Reference: [Testing Guide](docs/testing-guide.md), [Deployment Guide](docs/deployment-guide.md), [Troubleshooting](docs/guides/troubleshooting.md), [Full Documentation Index](docs/README.md)


## CLI Reference

The `asbs` CLI scaffolds projects and components:

```bash
asbs setup <project-name>                        # Create a new project
asbs create handler <name> [--event-type <type>]  # Add an event handler
asbs create service <name>                        # Add a business service
asbs create api <name>                            # Add a REST API
asbs create agent <name>                          # Add an AI agent
asbs create scheduler <name> [--cron <expr>]      # Add a scheduler
asbs validate                                     # Validate project structure
asbs dev [--port <port>]                          # Run development server
```

See the full [CLI Reference](docs/guides/cli-reference.md).


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
