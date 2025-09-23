# Base Framework

This directory contains the core framework components for the Agent Blueprint. These components provide the foundational functionality that should **NOT** be modified when implementing a new agent.

## Structure

```
base/src/
├── agent/          # Base agent runtime and framework
├── api/            # Framework API components (actuators, deps)
├── gateways/       # Data gateway clients
├── models/         # Base domain models
├── app.py          # FastAPI application factory
├── config.py       # Configuration management
└── telemetry.py    # Observability and tracing
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

This framework is designed to be imported by agent implementations in the `agent/` directory. The framework provides the infrastructure while the agent implementation provides the business logic.

## Modification Policy

**DO NOT MODIFY** these files when implementing a new agent. Instead, extend the base classes and implement the abstract methods in your agent implementation.

If you need to modify the framework itself, ensure that changes are backward compatible and don't break existing agent implementations.
