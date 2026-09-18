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
(its `settings.toml`, its `src/prompts`), relative to the **image root** -- the directory the
process runs in, which is usually the one holding `agents.toml` but does not have to be:
`BLUEPRINT_AGENT_MAP` moves the map without moving the agents, and `asbs validate --group
--agent-map <path>` checks that layout. `module` is how its code imports. A root guessed from where the declaration sits is right for one layout and
silently wrong for the rest -- and an agent whose settings were looked for in the wrong place does
not fail, it runs on the group's defaults and says nothing.

**Migrating an existing agent: check the file's contents, not just its place.** An agent's
`settings.toml` becomes its scope when merged, so a `[default.<agent>]` section inside it nests to
`<agent>.<agent>.*` and is read by nothing -- surfacing later as a missing model name that blames
the agent, not the file. Unprefix to plain `[default]`; that serves both shapes.

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

| Shape | Command | Needs group config? |
|---|---|---|
| Standalone, from before the split | `uvicorn src.main:app` | no |
| Standalone | `uvicorn src.main:create_app --factory` | no |
| One agent of a group | `python -m blueprint.agents.entrypoint` | yes: an agent map and a group |

A standalone agent declares **nothing** group-related -- no agent map, no group, no namespace. A
group of one is still a group, and an agent must not have to declare itself one to run alone.
Its components are built at the root namespace, so the routes are the ones the API declares;
hosted in a group, the same directory gains an `/api/<agent>` prefix.

## Supplying the group

The map is baked in; the group is not. One image serves every group, so which agents *this*
process runs arrives at container start, by one of two routes.

**Environment only**, which is the `docker run` and CI shape. No file is read at all:

```bash
docker run -e BLUEPRINT_AGENTS=order,billing -e BLUEPRINT_CRITICAL_AGENTS=order my-image
```

**A mounted group file**, which is what a real deployment usually does, because the composition
is then something reviewable as a diff:

```yaml
groups:
  - name: checkout
    agents: [order, billing]
    critical_agents: [order]
```

| Variable | Default | Meaning |
|---|---|---|
| `BLUEPRINT_GROUP_CONFIG` | `./deployment-groups.yaml` | Path to the group file |
| `BLUEPRINT_GROUP` | -- | Which group in it. Optional when the file declares exactly one |
| `BLUEPRINT_AGENTS` | -- | Comma-separated names, supplying the group with no file at all |
| `BLUEPRINT_CRITICAL_AGENTS` | -- | Comma-separated subset to mark critical |
| `BLUEPRINT_AGENT_MAP` | `./agents.toml` | Path to the map |

The environment overrides the file key by key, so one deployment changes the agent list without
editing or duplicating a mounted file. Setting `BLUEPRINT_AGENTS` while `BLUEPRINT_GROUP` is
unset skips the file entirely rather than merging with it.

### Several groups: one file, or one file each

`BLUEPRINT_GROUP_CONFIG` takes a **path**, so both shapes work and the framework has no opinion
about which. One file holding every group is the default name and reviews as a single diff. One
file per group keeps a typo in one group out of every other group's container:

```
deployment/groups/          # an example. Any layout works -- only the path has to be right
  checkout.yaml
  reporting.yaml
```

```bash
docker run -v ./deployment/groups/checkout.yaml:/app/group.yaml:ro \
           -e BLUEPRINT_GROUP_CONFIG=/app/group.yaml \
           -e BLUEPRINT_GROUP=checkout \
           my-image
```

Each such file still carries the `groups:` list with its one entry -- there is no single-group
form, and the same file works unchanged if it is later merged back into a shared one.

**Set `BLUEPRINT_GROUP` even though a sole group makes it optional.** It is what catches the
wrong file being mounted: a name that is not in the file is refused by name, where an unnamed
sole group is taken silently whatever it turns out to contain.

**Whatever the layout, add it to `.dockerignore`.** The scaffolded one excludes
`deployment-groups.yaml` by name and nothing else, and `.gitignore` does not apply to a build
context. A group file baked into a layer makes the image serve the group that happened to be on
disk when it was built, which is the opposite of the point.

If the group cannot be resolved -- nothing naming agents, a group absent from the file, an agent
the image does not contain -- the process prints one line and **exits before binding its port**,
so an orchestrator restarts it with something actionable rather than reporting a healthy replica
that is quietly short a consumer.

## Before promising the move is free

An agent **left standalone** is unaffected by any of this. An agent **moved into a group** changes
its broker-side identity once, and its cache starts cold. Both are set out under *What changes, and
what does not* in `guides/multi-agent-setup` - read that section before telling anyone the migration
is invisible, because for a migrated agent it is not.

Run `asbs validate` after migrating. It reads files only, never imports the project, and checks the
namespace alphabet, the agent map and the module attribute.
