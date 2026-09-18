# Migrating an Existing Agent into a Group

You have a single-agent project with a `main.py` that builds and serves an application, and you
want it to run beside other agents in one process. Three files change, and nothing else.

Migrating is optional. A project deployed on its own keeps working, unchanged, indefinitely --
there is no deprecation here. See [Multi-Agent Setup](multi-agent-setup.md) for the model this fits into, and
read [the one decision to get right first](multi-agent-setup.md#the-one-decision-to-get-right-first) before you
start: one of the three files carries a name you cannot cheaply change afterwards.

---

Three files change, and nothing else. Read
[the one decision to get right first](multi-agent-setup.md#the-one-decision-to-get-right-first) before you start: one
of the three is a name you cannot cheaply change afterwards.

## 1. `src/main.py` -- remove two things, add nothing

Before:

```python
config = Config(settings_files=["settings.toml", ".secrets.toml"])

app = (
    AppBuilder(config)
    .with_service(OrderService)
    .with_handler(OrderValidationHandler)
    .with_rest_api(OrderApi)
    .with_cache()
    .build()
)
```

After -- **the same builder**, minus its `config` argument and minus the `.build()`:

```python
agent = (
    AppBuilder()
    .with_service(OrderService)
    .with_handler(OrderValidationHandler)
    .with_rest_api(OrderApi)
    .with_cache()
)
```

Every `with_*` call stays exactly where it was. `with_cache()` included. That is the point of there
being one builder class: migration removes two things and adds none, because the declaration and
the application builder are the same object.

If the agent is **also** still to be served on its own, add a factory -- optional, and it repeats no
component:

```python
def create_app():
    return agent.build(Config(settings_files=["settings.toml", ".secrets.toml"]))
```

Two things the module must not do, because it is imported into a shared runtime: construct clients
or other components at import time, and call `logging.basicConfig()`. Configuration and logging
belong to the process that hosts the declaration.

If you are passing **instances** anywhere -- `with_rest_api(OrderApi())` -- change them to classes.
An instance is constructed at that line, before any namespace exists, so it belongs to the root for
ever; a group refuses one at assembly and names the agent and the fix.

## 2. `Dockerfile` -- one command

```diff
-CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
+CMD ["python", "-m", "blueprint.agents.entrypoint"]
```

and copy the map into the image beside your settings:

```dockerfile
COPY --chown=appuser:appuser agents.toml ./
```

**That command is not sufficient on its own, and copying the map does not complete it.** Where
`uvicorn src.main:app` named the application it served, the entry point has to be *told* which
agents to run, and the map says only which ones the image contains. A container given neither
`BLUEPRINT_AGENTS` nor a group file prints one line and exits before binding its port:

```
Cannot start: No agents were resolved for this process. ...
```

Supply it per run -- `-e BLUEPRINT_AGENTS=order`, or a mounted group file with
`-e BLUEPRINT_GROUP=<name>` -- or bake a development default the deployment overrides:

```dockerfile
ENV BLUEPRINT_AGENTS="order"
```

There is no default and no "every agent in the map". That refusal is deliberate: a fallback of
"run everything in the image" would make adding an agent to the map silently change what every
existing deployment runs -- new consumers, new durables, new routes -- with no deployment edit at
all. See [Environment](multi-agent-setup.md#environment) for the variables, and
[One file, or one file per group](multi-agent-setup.md#one-file-or-one-file-per-group) for where
the file itself lives.

## 3. The image's `agents.toml` -- one entry, not a new file here

The entry goes in the **image's** map, at the top of the repository that builds the image --
not in the agent's directory. The map says which agents an image contains, which is a packaging
decision; an agent that carried one would be an agent that knows whether it is running alone.
`asbs validate --group` refuses one found inside an agent.

If the repository has no image files yet, create them once:

```bash
asbs setup --group
```

Then add this agent:

```toml
[agents.order]
root   = "agents/order"
module = "agents.order.src.main:agent"
```

**Both keys are required.** `root` is the agent's own directory -- the one holding its
`settings.toml` and its `src/` -- relative to the image root, which is the directory the process
runs in and normally the one holding `agents.toml`. `module` is how its
code imports. Neither is derived from the other: a root guessed from where the declaration sits
is right for one layout and silently wrong for the rest, and an agent whose settings were looked
for in the wrong place does not fail, it runs on the group's defaults without saying so.

Nothing inside the agent's directory moves. Its `settings.toml` stays beside `src/`, exactly
where it was when the project ran on its own -- that sameness is what lets the directory move
back out again untouched.

### One thing inside the file may have to change

The location does not move; the *contents* might. This file **becomes** the agent's scope when it
is merged, so it must not scope keys itself:

```toml
# Wrong in a group: nests to risk_identifier.risk_identifier.*, and nothing reads it
[default.risk_identifier]
model_name = "..."

# Right, and works standalone too
[default]
model_name = "..."
```

A standalone project may well carry the prefixed form today, because a scoped lookup falls back to
the root key and both resolve. Once the file is merged under the agent's namespace the prefix nests
a second time and every key under it becomes unreachable -- which surfaces far from the cause, as
something like `No model name for runtime agent 'risk_identifier_agent' configured`, naming the
agent rather than the file.

The merge refuses this outright, and `asbs validate --group` reports it without starting anything.
Unprefixing to plain `[default]` serves both shapes, so there is no second file to keep.

Only for a group. Running this agent on its own needs no map at all -- `uvicorn
src.main:create_app --factory` builds the declaration directly. In a group the map is the only
thing that turns an agent's name into code.
There is discovery by convention nowhere in this, deliberately -- a set of agents that depends
on what happens to be importable makes a renamed directory a silently removed agent. Renaming
or moving an agent directory means updating its entry here, and until you do, the process
refuses to start rather than quietly dropping the agent.

### Process-wide keys move up

If the project's `settings.toml` sets `app_port`, `app_host`, `app_environment`, `event_bus`,
`log_level`, `log_format` or the other keys that describe the process, they belong in the
**image's** `settings.toml` now. One process has one of each, so a copy under an agent is
dropped before the merge with a warning naming the value actually used.

## 4. Check it

```bash
asbs validate              # inside the agent's directory: the agent itself
asbs validate --group      # at the top: the map, and every agent it points at
```

`--group` resolves every `root`, reports which `settings.toml` each agent actually reads, refuses a
file sitting where the framework will not look for it, and names process-wide keys left in an
agent. Neither imports your project.

## One declaration, three ways to run it

| Shape | Command | Needs group config? |
|---|---|---|
| Standalone, from before the split | `uvicorn src.main:app` | no |
| Standalone | `uvicorn src.main:create_app --factory` | no |
| One agent of a group | `python -m blueprint.agents.entrypoint` | yes: an agent map and a group |

A standalone agent declares **nothing** group-related -- no agent map, no group, no namespace. A
group of one is still a group, and an agent must not have to declare itself one to run alone.
Its components are built at the root namespace, so the routes are the ones the API declares;
hosted in a group, the same directory gains an `/api/<agent>` prefix.

---

## After the move

Your **broker-side identity changes once**, on the first grouped deploy. What that affects --
durables, queue groups, cache directories, telemetry -- is set out in
[What changes, and what does not](multi-agent-setup.md#what-changes-and-what-does-not), and the cold-cache
consequence in [The cache is cold after the move](multi-agent-setup.md#the-cache-is-cold-after-the-move).

---

## See also

- [Multi-Agent Setup](multi-agent-setup.md) -- the model, a new project, and group configuration
- [CLI Reference](cli-reference.md) -- `asbs validate` checks the migration for you
- [Deployment](deployment.md) -- images, Helm, probes, scaling
