# AVS Blueprint Agents Base Framework

This directory contains the core framework components for the Agent Blueprint. These components provide the foundational functionality that should **NOT** be modified when implementing a new agent.

## Installation

Install the framework from PyPI:

```bash
pip install avs-blueprint-agents
```

## Module Layout

The package is published under the namespace `agents.base`. When developing
locally, the corresponding sources live under `base/src/` and mirror the same
module layout:

```
agents/base/
├── agent/          # Base agent runtime and framework components
├── api/            # REST layer (actuators, dependencies, REST base class)
├── gateways/       # Shared gateway clients
├── models/         # Core domain/value models
├── services/       # Application services (processing, health, publishing)
├── registry/       # Component and service registries
├── app_builder.py  # FastAPI application builder
├── config/         # Configuration helpers (Dynaconf integration, logging)
└── telemetry.py    # Observability helpers
```

## Key Components

- **`config.py`**: Configuration management using Dynaconf
- **`telemetry.py`**: OpenTelemetry setup and instrumentation
- **`app.py`**: FastAPI application factory with middleware setup
- **`agent/base/`**: Abstract base classes for agent runtime
- **`api/actuators.py`**: Health check and monitoring endpoints
- **`api/deps.py`**: Dependency injection framework
- **`gateways/`**: Data gateway client implementations
- **`models/`**: Base domain models and event structures

## Usage

This framework is designed to be imported by agent implementations. The framework provides the infrastructure while the agent implementation provides the business logic.

Example imports:

```python
from agents.base.api.rest import RestApi
from agents.base.agent.agent_builder import AgentBuilder
```

## Modification Policy

**DO NOT MODIFY** these files when implementing a new agent. Instead, extend the base classes and implement the abstract methods in your agent implementation.

If you need to modify the framework itself, ensure that changes are backward compatible and don't break existing agent implementations.
