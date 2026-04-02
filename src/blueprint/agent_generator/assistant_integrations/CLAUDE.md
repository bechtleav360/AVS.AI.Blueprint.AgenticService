# Claude Code Guidelines

This file is read automatically by Claude Code at the start of every session.

## Framework

This project uses the **Blueprint Agents** framework. All application components extend
base classes from the framework:

| Class | Import | Purpose |
|---|---|---|
| `EventHandlerBase` | `blueprint.agents.handler` | CloudEvent processing (chain-of-responsibility) |
| `ServiceBase` | `blueprint.agents.services` | Domain logic, state, orchestration |
| `AgentRuntime` | via `AgentBuilder` from `blueprint.agents` | LLM agents (wraps pydantic-ai) |
| `RestApiBase` | `blueprint.agents.io.api` | HTTP endpoints via FastAPI |
| `SchedulerBase` | `blueprint.agents.io.api.scheduling` | Background cron tasks |

## Key Architecture Rules

- **Never access `self.registry` or `self.config` in `__init__`** — they are not linked until after construction. Always resolve dependencies in `on_startup()`.
- **Register dependencies before dependents** — services before handlers/agents that use them.
- **`main.py` is wiring only** — no business logic.
- **Services contain ALL business logic** — handlers and APIs are thin delegation layers with one method per responsibility.
- No global state, no module-level component instances.

```python
# Correct — resolve in on_startup()
class MyHandler(EventHandlerBase):
    async def on_startup(self) -> None:
        self._service = self.registry.get_service(MyService)
```

## Code Style

- Complete type hints on every method signature
- All I/O must be `async` / `await` — never blocking I/O in async code
- Every public method needs a docstring (one-liner is fine for simple methods)
- Use `%s`-style args in log calls, not f-strings (deferred formatting)
- Validate all external input with Pydantic at system boundaries
- Never hardcode secrets — use environment variables via `secrets.toml`
- **No `assert` statements in production code** — `assert` is only permitted in test files (`tests/`)
- **All imports at the top of the file** — never inside methods, functions, or classes

## Agent Prompts

- **System prompt** (`system.prompt`): Static context — no dynamic inputs. Loaded by `AgentBuilder.with_system_prompt()`.
- **Instruction prompt** (`instruction.prompt`): Contains `{placeholders}` for dynamic inputs.
- Files go in `src/prompts/` as `.prompt` files

**Always use `agent.get_prompt().format()` for user prompts with variable inputs:**

```python
prompt = self._agent.get_prompt("instruction").format(
    ticket_text=ticket_text,
    customer_tier=customer_tier,
)
result = await self._agent.run(user_prompt=prompt)
```

## Error Handling

- Define domain-specific exceptions when callers need to catch them selectively
- Always use context managers (`async with`) for files, HTTP clients, DB connections
- Set explicit timeouts on all external calls
- Never log passwords, tokens, or API keys

## Testing

- Test files: `test_<module>.py` | Classes: `Test<Component>` | Methods: `test_<behavior>_<result>`
- Use `MagicMock(spec=...)` for sync deps, `AsyncMock()` for async deps
- Shared fixtures in `conftest.py`
- `asyncio_mode = auto` in `pytest.ini`

## Project Structure

```
src/
├── main.py          # AppBuilder wiring only
├── api/             # RestApiBase subclasses
├── handlers/        # EventHandlerBase subclasses
├── services/        # ServiceBase subclasses
├── schedulers/      # SchedulerBase subclasses
├── agents/          # AgentBuilder setup code
├── models/          # Pydantic models
└── prompts/         # .prompt files (system + instruction)
```

## Running the Service

```bash
pip install -e .
uvicorn src.main:app --reload     # development
pytest tests/                      # run tests
asbs validate                      # validate project structure
```
