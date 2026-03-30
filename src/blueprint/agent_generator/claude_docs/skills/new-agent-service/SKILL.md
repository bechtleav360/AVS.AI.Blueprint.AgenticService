---
name: new-agent-service
description: Scaffold a complete new Blueprint Agents service from a user description. Use when the user wants to create a new agentic microservice project from scratch.
user-invocable: true
---

# New Agent Service

You are scaffolding a new Blueprint Agents microservice. Follow these steps precisely.

## Step 1: Gather Requirements

If the user provided a description, extract from it:
- **Service name** (kebab-case, e.g., `invoice-processor`)
- **What events it handles** (event types and their data)
- **What LLM agents it needs** (names, purposes, expected outputs)
- **What REST endpoints it exposes** (if any)
- **What scheduled tasks it runs** (if any)

If any of these are unclear, ask the user ONE focused question before proceeding.

## Step 2: Check for Existing Project

Check if a project already exists at the target location (look for `src/main.py` or `pyproject.toml`).

- **If no project exists**: Run `asbs setup <project-name>` to scaffold the project skeleton first.
- **If a project already exists**: Skip scaffolding and work with the existing structure.

## Step 3: Architecture Planning

Use the `blueprint-architect` agent to produce an architecture plan based on the requirements. The architect will determine:
- Which components are needed (handlers, services, agents, APIs, schedulers)
- The dependency graph between components
- The wiring order in `main.py`
- Configuration structure (settings.toml, secrets.toml)

## Step 4: Implementation

Use the `blueprint-builder` agent to implement each component from the architecture plan. The builder will:
- Create all component files using `asbs create` CLI commands for consistency
- Implement business logic in services with well-separated methods for each responsibility
- Configure agents with system and instruction prompts, tools, and result types
- Wire everything in `main.py` using `AppBuilder`
- Create Pydantic models for domain objects and DTOs
- Write prompt files in `src/prompts/` (system prompt: static context; instruction prompt: dynamic inputs)

## Step 5: Configuration

Ensure `settings.toml` has:
- App name and environment
- Model provider and model name for each agent runtime
- Event publishing topic mappings (if handlers publish events)
- Cache settings (if caching is used)

Ensure `secrets.toml` has placeholder keys for any required API keys.

## Step 6: Verification

- Run `asbs validate` to check project structure
- Verify all imports resolve correctly
- Confirm `main.py` registers components in correct dependency order
- Run `pytest tests/` if test files were generated

## Rules

- **Always use `asbs create` commands** to generate component files — never create them manually
- **Only run `asbs setup` if no project exists** — never scaffold over an existing project
- **Follow the wiring order**: services first, then agents, then handlers/APIs/schedulers
- **Never put business logic in `main.py`** — it is wiring only
- **Never access `self.registry` or `self.config` in `__init__`** — use `on_startup()`
- **All models must be Pydantic BaseModel subclasses** with complete type hints
- **Agent prompts**: system prompt is static (no dynamic inputs), instruction prompt contains dynamic inputs
