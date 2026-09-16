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

**Both keys are required.** `root` is the agent's own directory, relative to the directory
`agents.toml` is in -- the one holding its `settings.toml` and its `src/`. `module` is how its
code imports. Neither is derived from the other: a root guessed from where the declaration sits
is right for one layout and silently wrong for the rest, and an agent whose settings were looked
for in the wrong place does not fail, it runs on the group's defaults without saying so.

Nothing inside the agent's directory moves. Its `settings.toml` stays beside `src/`, exactly
where it was when the project ran on its own -- that sameness is what lets the directory move
back out again untouched.

Required even for a group of one: it is the only thing that turns an agent's name into code.
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

| Shape | Command |
|---|---|
| Standalone, unmigrated | `uvicorn src.main:app` |
| Standalone, migrated (with `create_app`) | `uvicorn src.main:create_app --factory` |
| Grouped, including a group of one | `python -m blueprint.agents.entrypoint` |

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
