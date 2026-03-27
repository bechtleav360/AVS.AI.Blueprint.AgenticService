# Blueprint Framework

Python framework for event-driven AI agent microservices. All logic lives in one of five component types wired by `AppBuilder`.

## Five Components

| Component | Base class | Purpose | Register via |
|-----------|-----------|---------|-------------|
| `EventHandler` | `blueprint.agents.base` | Process CloudEvents (chain-of-responsibility) | `.with_handler()` |
| `BusinessService` | `blueprint.agents.base` | Shared domain logic and state | `.with_service()` |
| `AgentRuntime` | `blueprint.agents.agent` → `AgentBuilder` | LLM agent (pydantic-ai) | `.with_agent()` |
| `Scheduler` | `blueprint.agents.base` | Background cron tasks | `.with_scheduler()` |
| `RestApi` | `blueprint.agents.base` | FastAPI HTTP endpoints | `.with_rest_api()` |

## Registration Order (ALWAYS follow this)

```python
AppBuilder(config).with_service(...).with_agent(...).with_handler(...).with_scheduler(...).with_rest_api(...).build()
```

## Critical Rules

1. **Never call `get_registry()` or `get_config()` in `__init__`** — raises `RuntimeError`. Always in `on_startup()`.
2. **Register dependencies before dependents** — services before handlers/schedulers that use them.
3. **No direct cross-component imports** — use `self.get_registry()`.

## Skills Available

| Skill | When to use |
|-------|------------|
| `/new-agent-service [description]` | Build a complete new service from requirements |
| `/create-handler [event-type] [name]` | Add an EventHandler |
| `/create-service [name]` | Add a BusinessService |
| `/create-scheduler [cron] [name]` | Add a Scheduler |
| `/create-agent-runtime [name]` | Add an AgentRuntime via AgentBuilder |
| `/create-rest-api [resource]` | Add a RestApi with FastAPI routes |

## Agents Available

- `@blueprint-architect` — Analyze requirements, decide components, produce architecture plan
- `@blueprint-builder` — Build complete components or services, create all files
