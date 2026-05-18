---
name: add-component
description: Add a single Blueprint component (handler, service, api, agent, scheduler) to an existing project. Use when the user wants to add one component, not scaffold a full project.
user-invocable: true
---

# Add Component

You are adding a single component to an existing Blueprint Agents project.

## Step 1: Determine Component Type

Parse the user's request to identify:
- **Component type**: handler, service, api, agent, or scheduler
- **Component name**: UpperCamelCase (e.g., `OrderProcessor`)
- **Additional details**: event type (handlers), cron expression (schedulers), endpoints (APIs)

If the type or name is ambiguous, ask ONE clarifying question.

## Step 2: Scaffold with CLI

Use the appropriate `asbs create` command:

```bash
# EventHandler
asbs create handler <Name> --event-type <type> --priority <n>

# Service
asbs create service <Name>

# RestApi
asbs create api <Name>

# AgentRuntime
asbs create agent <Name>

# Scheduler
asbs create scheduler <Name> --cron "<cron-expression>"
```

## Step 3: Implement

After scaffolding, implement the component logic:

1. **Read the generated file** to understand the skeleton
2. **Read `src/main.py`** to understand existing wiring and available dependencies
3. **Implement the component** following these patterns:

### EventHandler
- `can_handle_event()`: Filter by `event.type` or event data
- `handle_event()`: Process event, return `HandlerResult` or `None`
- Resolve service dependencies in `on_startup()` via `self.registry.get_service()`

### Service
- Add domain methods with clear input/output types
- Resolve agent/cache dependencies in `on_startup()`

### RestApi
- Use `@RestApiBase.get/post/put/delete/patch()` decorators
- Use Pydantic models for request/response types
- Resolve services in `on_startup()`

### AgentRuntime
- Configure via `AgentBuilder` in `main.py` (not in a separate file)
- Set system prompt, tools, result type, and model config
- Create `.prompt` file in `src/prompts/` if needed

### Scheduler
- Implement `tick()` with the recurring logic
- Resolve dependencies in `on_startup()`

## Step 4: Wire into main.py

Add the component to the `AppBuilder` chain in `src/main.py`:
- Import the new component
- Add the appropriate `.with_*()` call in dependency order
- For agents: add `AgentBuilder` setup before the `AppBuilder` chain

## Step 5: Update Configuration

If the component needs configuration:
- Add runtime config to `settings.toml` under `[default.runtimes.<name>]` for agents
- Add topic mappings under `[default.event_publishing]` for handlers that publish events
- Add API key placeholders to `secrets.toml` for new AI providers

## Rules

- **Always use `asbs create`** to generate the file skeleton first
- **Never access `self.registry` or `self.config` in `__init__`** — use `on_startup()`
- **Register in correct order** in `main.py`: services → agents → handlers/APIs/schedulers
- **Type hints on every method signature**
- **Pydantic models for all API request/response types**
