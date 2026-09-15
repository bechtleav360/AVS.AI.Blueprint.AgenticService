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
