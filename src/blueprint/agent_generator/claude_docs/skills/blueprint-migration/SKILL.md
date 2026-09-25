---
name: blueprint-migration
description: Migrating an existing single-agent Blueprint project so it runs in a multi-agent group - rewriting src/main.py into a declaration, the Dockerfile entry point, the agents.toml entry, and the settings.toml edits the move may need. Use when an existing agent must join a group, or when a migrated agent will not start or runs without its settings.
user-invocable: true
---

# Migrating an Agent into a Group

**Read the guide before editing anything** - it has the before/after for every file:

```bash
asbs docs guides/multi-agent-migration --cat    # the four steps, with diffs
asbs docs guides/multi-agent-setup --cat        # the model it fits into, and what changes after
```

Migrating is optional. A project left standalone keeps working unchanged, with no deprecation - ask
whether the move is actually wanted before starting it.

## Choose the name first

The agent's name in `agents.toml` becomes its queue group, its JetStream durables, its cache
directory and Redis prefix, its telemetry `service.name` and its `/api/<agent>` route prefix.
Renaming it after the first grouped deploy is a consumer migration, not a rename. The alphabet is
`[a-z][a-z0-9_]*` - **no dashes**; a name outside it is refused, never repaired. See
`blueprint-multi-agent` for why.

## What changes

Three files carry the migration; two more may need an edit.

| File | Change |
|---|---|
| `src/main.py` | `AppBuilder(config)...build()` becomes `agent = AppBuilder()...` - drop the `config` argument and the `.build()`, keep every `with_*` call |
| `Dockerfile` | `CMD ["python", "-m", "blueprint.agents.entrypoint"]`, and copy `agents.toml` into the image |
| image's `agents.toml` | one `[agents.<name>]` entry with **both** `root` and `module` |
| agent's `settings.toml` | only if it scopes keys as `[default.<agent>]`: unprefix to `[default]` |
| image's `settings.toml` | only if the agent sets process-wide keys (`app_port`, `event_bus`, `log_level`, ...): move them up |

Nothing inside the agent's directory moves. Its `settings.toml` stays beside `src/`.

## Rules that bite

- **Classes, not instances.** `with_rest_api(OrderApi())` is built before any namespace exists; a
  group refuses it. Pass `OrderApi`.
- **Nothing at import time.** The module is imported into a shared runtime: no client construction,
  no `logging.basicConfig()`.
- **Still serving it alone?** Add `def create_app(): return agent.build(Config(...))` and run
  `uvicorn src.main:create_app --factory`. It repeats no component.
- **The new `CMD` alone does not start.** The map says which agents the image *contains*, not which
  this process *runs*. Without `BLUEPRINT_AGENTS` or a group file the container exits before
  binding its port - by design, there is no "run everything" default.
- **The map belongs to the image, never the agent.** `asbs setup --group` creates the image files
  if the repository has none. An `agents.toml` inside an agent's directory is refused.
- **`root` and `module` are never derived from each other.** A wrong `root` does not fail - the
  agent silently runs on the group's defaults. `root` resolves against the image root, not the map.
- **`[default.<agent>]` nests twice once merged** and every key under it becomes unreachable. It
  surfaces as a missing model name blaming the agent, not the file. Plain `[default]` serves both
  shapes.

## Check it

```bash
asbs validate              # inside the agent's directory
asbs validate --group      # where the map is: the map and every agent it names
```

`--group` resolves each `root`, reports which `settings.toml` each agent reads, and flags prefixed
sections and process-wide keys left in an agent. Pass `--agent-map <path>` if the map is not
beside the directory being checked.

## Before calling the move invisible

It is not. On the first grouped deploy the agent's broker-side identity changes once (new durables,
new queue group) and its cache starts cold. Read *What changes, and what does not* in
`guides/multi-agent-setup` before telling anyone otherwise.
