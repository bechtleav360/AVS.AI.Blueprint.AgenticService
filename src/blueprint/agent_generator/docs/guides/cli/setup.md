# asbs setup

Scaffold a complete Blueprint Agents project with all required directories and configuration files.

```bash
asbs setup <project-name> [--output-dir <dir>] [--overwrite] [--verbose]
asbs setup --group [--output-dir <dir>] [--overwrite]
```

## Arguments

| Argument       | Description                        | Required |
|----------------|------------------------------------|----------|
| `project-name` | The agent's name                   | Yes, unless `--group` |

## Options

| Flag                  | Description                                            | Default |
|-----------------------|--------------------------------------------------------|---------|
| `--group`             | Write the image's files instead of an agent; see [below](#asbs-setup---group) | off |
| `--output-dir <dir>`  | Directory to scaffold into -- the project itself; it must exist | `.`     |
| `--overwrite`         | Overwrite existing files instead of refusing           | off     |
| `--verbose`, `-v`     | Debug-level logging from the generator                 | off     |

The project is written **into** the output directory, not into a subdirectory named after it:
create the directory first and run `asbs setup` inside it. A directory that already holds `src/`
or `settings.toml` is refused unless `--overwrite` is given.

The project name is normalised to a class name prefix (`order-processor` gives `OrderProcessor`),
and the agent's namespace is that name in snake case (`order_processor`). The namespace is checked
before anything is written: a name whose snake case does not match `[a-z][a-z0-9_]*`, or that is
one of the reserved names `cache`, `event_publishing`, `runtimes` and `runtime`, is refused.

## Generated Project Structure

```
<output-dir>/
  src/
    main.py            # the declaration: agent = AppBuilder()...
    api/
    handlers/
    models/<name>/     # dto.py, domain_models.py, mapper.py
    prompts/
    services/
  tests/               # conftest.py, test_declaration.py, test_mapper.py
  settings.toml
  .secrets.toml          # git-ignored
  .secrets.toml.example  # committed, so the keys to fill in are known
  pyproject.toml         # only if the directory has none
  Dockerfile
  .dockerignore
  .gitignore
```

There is no `agents.toml`. The agent map says which agents an *image* contains, which is a
packaging decision -- an agent that carried one would be an agent that knows whether it is running
alone. The generated `Dockerfile` needs none: it serves `create_app()` directly, at the root
namespace. A group image maps the agent in the repository's `agents.toml`; `asbs dev --name`
supplies a name while developing. `asbs validate --group` refuses a map found inside an agent.

A `pyproject.toml` is written only if the directory has none: `asbs` runs from the project's own
environment, so by then there is usually one already, with somebody's dependencies in it.

## Example

```bash
mkdir my-ai-service && cd my-ai-service
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
group refuses one, and so does `create_app()`.

**`asbs setup` writes no `agents.toml`, and that is deliberate.** The map says which agents an
*image* contains, so an agent carrying one would be an agent that knows whether it is running
alone -- and `asbs validate --group` refuses one found inside an agent. The project is run with `uvicorn
src.main:create_app --factory`, which needs no map, no group and no namespace.

Whoever hosts it supplies the name. To host this directory in a group, add it to the **image's**
map, which lives in the repository that builds the image:

```toml
[agents.my_ai_service]
root   = "<path from that file to this directory>"
module = "<that path as a dotted package>.src.main:agent"
```

Both keys are required, and `root` resolves against the image root rather than against the map.
See [Multi-Agent Migration](../multi-agent-migration.md) for the three files that change.

That name is the agent's identity everywhere outside the file -- the NATS queue group, part of the
JetStream durable name, the cache partition, the OpenTelemetry `service.name` and the `/api/<name>`
route prefix -- so changing it after the first deploy is a consumer migration.

---

## asbs setup --group

The other mode. It writes the *image's* files and creates no agent:

```bash
asbs setup --group
```

```
agents.toml     # empty: this image contains no agents yet
settings.toml   # the process: app_port, app_host, event_bus, log_level
Dockerfile      # the group image
.dockerignore   # keeps every agent's .secrets.toml and the group file out of the image
.gitignore
pyproject.toml  # the image's dependencies; only if the directory has none
```

No agent is created and none is named, because which agents an image contains is decided one
`asbs setup <name>` at a time, in whatever directories suit the repository. An image with no
agents cannot start -- the process refuses rather than binding a port and consuming nothing --
so add an entry per agent before deploying it:

```bash
mkdir -p agents/some_topic/my_agent
cd agents/some_topic/my_agent
asbs setup my_agent
```

```toml
[agents.my_agent]
root   = "agents/some_topic/my_agent"
module = "agents.some_topic.my_agent.src.main:agent"
```

Both keys are required. See [Multi-Agent Setup](../multi-agent-setup.md).
