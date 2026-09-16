---
name: blueprint-multi-agent
description: Running several Blueprint agents in one process, and migrating an existing single-agent project into a group. Use for agents.toml, agent namespaces, group deployment, the entrypoint module, or when an existing agent must join a group.
user-invocable: true
---

# Multi-Agent Groups

An agent's code says nothing about which other agents it runs beside. A project *declares* what it
is made of; a *deployment* decides which of those declarations a process hosts. Moving between the
two is an edit to a Deployment, not a rebuild.

## Which case is this?

| Case | Read |
|---|---|
| New project, built as a group from the start | `asbs docs guides/multi-agent-setup --cat` |
| Existing single-agent project joining a group | `asbs docs guides/multi-agent-migration --cat` |
| Leave it standalone | Nothing changes. There is no deprecation - this is a legitimate answer |

## The layout, which is not negotiable

An agent is **the same directory** alone or in a group -- that is what lets it move between
repositories untouched:

```
my_agent/
  settings.toml        # beside src/, never inside it
  .secrets.toml
  Dockerfile           # optional: builds this agent alone
  src/
    main.py            # the declaration
    prompts/
```

It carries **no `agents.toml`**. The map says which agents an *image* contains; an agent holding
one would be an agent that knows whether it is running alone. Whoever hosts it supplies the name:
a group image's map, a single-agent image's Dockerfile, or `asbs dev --name`.

The image, at the top of the repository:

```
agents.toml            # the map
settings.toml          # process-wide keys only
Dockerfile             # the group image
agents/...             # the agent directories, at any depth
```

Create them with two distinct modes -- `asbs setup --group` for the image, `asbs setup <name>`
inside each agent's directory. The agent command is identical to the standalone one.

## The map states both keys

```toml
[agents.my_agent]
root   = "agents/some_topic/my_agent"
module = "agents.some_topic.my_agent.src.main:agent"
```

**Both are required and neither is derived from the other.** `root` is where the agent's files are
(its `settings.toml`, its `src/prompts`), relative to the directory `agents.toml` is in; `module`
is how its code imports. A root guessed from where the declaration sits is right for one layout and
silently wrong for the rest -- and an agent whose settings were looked for in the wrong place does
not fail, it runs on the group's defaults and says nothing.

Run `asbs validate --group` after editing the map. It resolves every root, reports which
`settings.toml` each agent reads, and refuses a file that sits where nothing will read it.

## The decision to get right first

**The agent's name in `agents.toml` is its identity everywhere outside that file.** It becomes the
NATS queue group, part of every JetStream durable (`<agent>-<topic>-durable`), the cache directory
and Redis key prefix, the OpenTelemetry `service.name`, the route prefix `/api/<agent>`, and the
prefix on every registry key its components take.

Renaming it after the first grouped deploy is a **consumer migration** - new durables, messages
still pending on the old ones - not a rename. Choose it once, before deploying.

The namespace alphabet is **`[a-z][a-z0-9_]*`**: lower case, leading letter, underscores allowed,
**no dashes**. A name outside it is refused, never repaired. The dash is excluded because it
separates the parts of a durable name, so `orders-eu` on topic `created` and `orders` on topic
`eu-created` would otherwise produce the same durable and two agents would eat each other's events.

## Three ways to run one declaration

| Shape | Command |
|---|---|
| Standalone, unmigrated | `uvicorn src.main:app` |
| Standalone, migrated (with `create_app`) | `uvicorn src.main:create_app --factory` |
| Grouped, including a group of one | `python -m blueprint.agents.entrypoint` |

## Before promising the move is free

An agent **left standalone** is unaffected by any of this. An agent **moved into a group** changes
its broker-side identity once, and its cache starts cold. Both are set out under *What changes, and
what does not* in `guides/multi-agent-setup` - read that section before telling anyone the migration
is invisible, because for a migrated agent it is not.

Run `asbs validate` after migrating. It reads files only, never imports the project, and checks the
namespace alphabet, the agent map and the module attribute.
