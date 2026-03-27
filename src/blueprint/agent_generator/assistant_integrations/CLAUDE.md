# Claude Code Guidelines

This file is read automatically by Claude Code at the start of every session.

## Framework

This project uses the **Blueprint Agents** framework. All application components extend
one of five base classes from `blueprint.agents.base`:

| Class | Purpose |
|---|---|
| `BusinessService` | Domain logic and state |
| `EventHandler` | CloudEvent processing |
| `RestApi` | HTTP endpoints via FastAPI |
| `AgentRuntime` | LLM agents (wraps pydantic-ai) |
| `Scheduler` | Background cron tasks |

## Key Architecture Rules

- **Never instantiate dependencies in `__init__`** — resolve them via the registry in `on_startup()`
- **Never access config or registry in `__init__`** — they are not linked until after construction
- Dependencies flow downward only: handlers/APIs/schedulers → services → external I/O
- No global state, no module-level component instances
- `main.py` is for wiring only — no business logic

```python
# Correct
class MyHandler(EventHandler):
    async def on_startup(self) -> None:
        self._service = self.get_registry().get_service(MyService)
```

## Code Style

- Complete type hints on every method signature
- All I/O must be `async` / `await` — never blocking I/O in async code
- Every public method needs a docstring (one-liner is fine for simple methods)
- Use `%s`-style args in log calls, not f-strings (deferred formatting)
- Validate all external input with Pydantic at system boundaries
- Never hardcode secrets — use environment variables via `settings.toml`

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
- 80% line coverage is the minimum floor for business logic — not a target to chase

## Project Structure

```
src/
├── main.py          # AppBuilder wiring only
├── api/             # RestApi subclasses
├── handlers/        # EventHandler subclasses
├── services/        # BusinessService subclasses
├── schedulers/      # Scheduler subclasses
├── agents/          # AgentRuntime builder code
├── models/          # Pydantic models
└── prompts/         # Prompt files
```

## Running the Service

```bash
pip install -e .
uvicorn src.main:app --reload     # development
pytest tests/                      # run tests
pytest -m "not slow"               # fast suite only
```