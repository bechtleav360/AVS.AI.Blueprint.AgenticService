# asbs setup

Scaffold a complete Blueprint Agents project with all required directories and configuration files.

```bash
asbs setup <project-name> [--output-dir <dir>] [--overwrite] [--verbose]
```

## Arguments

| Argument       | Description                        | Required |
|----------------|------------------------------------|----------|
| `project-name` | Name of the project to create      | Yes      |

## Options

| Flag                  | Description                                            | Default |
|-----------------------|--------------------------------------------------------|---------|
| `--output-dir <dir>`  | Parent directory the project is created in             | `.`     |
| `--overwrite`         | Overwrite existing files instead of refusing           | off     |
| `--verbose`, `-v`     | Debug-level logging from the generator                 | off     |

The project name is normalised to a class name (`order-processor` gives `OrderProcessor/`), and the
agent's namespace is that name in snake case (`order_processor`).

## Generated Project Structure

```
<ProjectName>/
  src/
    main.py            # the declaration: agent = AppBuilder()...
    api/
    handlers/
    models/<name>/     # dto.py, domain_models.py, mapper.py
    prompts/
    services/
  agents.toml          # agent name -> declaration; baked into the image
  settings.toml
  .secrets.toml          # git-ignored
  .secrets.toml.example  # committed, so the keys to fill in are known
  Dockerfile
  .gitignore
```

There is no `tests/` directory and no `pyproject.toml`: the scaffolder writes source, settings and
the image, and the packaging and test layout are the project's own. `asbs validate` reports both as
missing, which is a reminder rather than a defect in the scaffold.

## Example

```bash
asbs setup my-ai-service
```

The generated `main.py` is a **declaration**, not an application. Nothing is constructed until
something calls `build()`, which is what lets the same file be served on its own and be hosted
alongside other agents in one process:

```python
from blueprint.agents.agent import AgentBuilder
from blueprint.agents.app_builder import AppBuilder

from .services import MyAiServiceService

my_ai_service_agent = (
    AgentBuilder(runtime_name="my_ai_service_agent")
    .with_model_from_config()
    .with_system_prompt("my_ai_service_agent_system")
)

agent = (
    AppBuilder()
    .with_service(MyAiServiceService)
    .with_agent(my_ai_service_agent, name="my_ai_service_agent")
)
```

Components are registered as **classes**, not instances: a component constructed on the `with_*`
line is constructed before any namespace exists and belongs to the root for ever, which is why a
group refuses one.

`asbs setup` also writes `agents.toml`, which maps the agent's name to that declaration:

```toml
[agents.my_ai_service]
module = "src.main:agent"
```

That name is the agent's identity everywhere outside the file -- the NATS queue group, part of the
JetStream durable name, the cache partition, the OpenTelemetry `service.name` and the `/api/<name>`
route prefix -- so changing it after the first deploy is a consumer migration. The project is run
with `python -m blueprint.agents.entrypoint`, which reads that map and the deployment's group.
