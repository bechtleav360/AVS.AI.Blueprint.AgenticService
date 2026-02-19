# Windsurf Documentation for Blueprint Agents Projects

This folder contains rules and workflows for Windsurf (Cascade AI) to help
developers building microservices on top of the **Blueprint Agents** framework.

## Folder structure

```
docs/windsurf/
├── README.md              ← this file
├── rules/                 ← reference documentation (Cascade reads these as context)
│   ├── architecture.md          Component model, dependency direction, file layout
│   ├── component-registry.md    How to use ComponentRegistry
│   ├── rest-api-routes.md       Annotation-based route registration
│   ├── business-service.md      BusinessService patterns
│   ├── event-handler.md         EventHandler / chain-of-responsibility
│   ├── scheduler.md             Scheduler / cron background tasks
│   └── agent-runtime.md         AgentRuntime / pydantic-ai LLM agents
└── workflows/             ← step-by-step slash commands for Cascade
    ├── create-rest-api.md
    ├── create-business-service.md
    ├── create-event-handler.md
    ├── create-scheduler.md
    ├── create-agent-runtime.md
    └── create-vscode-settings.md
```

## How to use

### Windsurf workflows (slash commands)

Type `/create-rest-api`, `/create-scheduler`, etc. in the Cascade chat panel
to trigger the corresponding workflow. Cascade will guide you through creating
the component with the correct patterns.

Available commands:

| Command | Creates |
|---------|---------|
| `/create-rest-api` | A `RestApi` subclass with annotation-based routes |
| `/create-business-service` | A `BusinessService` subclass |
| `/create-event-handler` | An `EventHandler` subclass |
| `/create-scheduler` | A `Scheduler` subclass with cron schedule |
| `/create-agent-runtime` | An `AgentRuntime` backed by a pydantic-ai LLM |
| `/create-vscode-settings` | `.vscode/launch.json`, `tasks.json`, `settings.json` |

### Rules (always-on context)

The files in `rules/` are loaded as persistent context by Windsurf. Cascade
will automatically follow the patterns described there when generating or
reviewing code in this project.

---

## Framework overview

```
blueprint.agents.base
├── Component          ← abstract base; provides get_config(), get_registry(), lifecycle hooks
├── BusinessService    ← domain logic; registered via AppBuilder.with_service()
├── EventHandler       ← CloudEvent processing; registered via AppBuilder.with_handler()
├── RestApi            ← FastAPI routes; registered via AppBuilder.with_rest_api()
├── AgentRuntime       ← pydantic-ai LLM agent; registered via AppBuilder.with_agent()
└── Scheduler          ← cron background task; registered via AppBuilder.with_scheduler()
```

### Minimal wiring example

```python
# src/main.py
from pathlib import Path
from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.config import Config

from .api import MyApi
from .handlers import MyHandler
from .schedulers import MyScheduler
from .services import MyService

config = Config(
    settings_files=[Path(__file__).parent.parent / "settings.toml"],
    root_path=Path(__file__).parent.parent,
)

app = (
    AppBuilder(config=config)
    .with_service(MyService())
    .with_handler(MyHandler())
    .with_scheduler(MyScheduler())
    .with_rest_api(MyApi())
    .build()
)
```

### settings.toml skeleton

```toml
[default]
app_name    = "My Service"
app_version = "0.1.0"
debug       = true

[default.server]
host = "0.0.0.0"
port = 8000

[default.logging]
level  = "INFO"
format = "json"

# LLM agent configuration (one block per runtime)
[default.runtimes.my_agent]
model_provider    = "openai"
model_name        = "gpt-4o"
model_api_key     = "@format {env[OPENAI_API_KEY]}"
model_max_tokens  = 2048
model_temperature = 0.1

[default.runtimes.my_agent.prompts]
system_prompt_name = "system"
```

### Project layout convention

```
my-service/
├── settings.toml
├── secrets.toml          ← gitignored; API keys go here
├── pyproject.toml
├── .vscode/
│   ├── launch.json
│   ├── tasks.json
│   └── settings.json
└── src/
    ├── main.py           ← AppBuilder wiring only
    ├── api/              ← RestApi subclasses
    ├── handlers/         ← EventHandler subclasses
    ├── schedulers/       ← Scheduler subclasses
    ├── services/         ← BusinessService subclasses
    ├── models/           ← Pydantic schemas
    └── prompts/          ← .prompt files for LLM agents
```

---

## Key rules (summary)

1. **Never call `get_registry()` or `get_config()` in `__init__`** — use `on_startup()`.
2. **Register dependencies before dependents** in `AppBuilder`.
3. **One component per file**, named after the class.
4. **Use `@RestApi.get/post/put/delete/patch`** for route registration — never `@self.router.*`.
5. **Schedulers: call `await super().on_startup()` last** — it starts the asyncio task.
6. **No global state** — no module-level component instances outside `main.py`.
7. **Names are registry keys** — keep them stable, lowercase, snake_case.
