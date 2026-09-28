---
name: blueprint-cli
description: Reference for the `asbs` command-line tool - scaffolding a project, adding components, validating, and running the dev server. Use when running or explaining any `asbs` command, or when a component needs to be created in a Blueprint Agents project.
user-invocable: true
---

# Blueprint CLI (`asbs`)

`asbs` is how components get created in this framework. **Always scaffold with `asbs create` rather
than writing component files by hand** - it applies the naming rules and registers the component in
`src/main.py`, and hand-written files miss both.

## Commands

```bash
asbs setup <project_name>                          # Scaffold one agent
asbs setup --group                                 # Scaffold the image's files instead
asbs create handler <name> [--event-type TYPE]     # Add EventHandler
asbs create service <name>                         # Add Service
asbs create api <name>                             # Add RestApi
asbs create agent <name>                           # Add AgentRuntime
asbs create scheduler <name> [--cron CRON]         # Add Scheduler
asbs validate [--group]                            # Check one agent, or a whole image
asbs dev [--name NAME] [--port 8000]               # Dev server with reload
asbs docs [<topic>] [--cat]                        # Locate the framework docs
```

## Read the detail before acting

Each command has its own page. Load only the one you need:

```bash
asbs docs guides/cli/setup --cat              # asbs setup, and what it generates
asbs docs guides/cli/create --cat             # all five component types, with examples
asbs docs guides/cli/validate --cat           # what validate checks, and the three grades
asbs docs guides/cli/dev --cat                # dev server options
asbs docs guides/cli/naming --cat             # how a typed name becomes a class and a file
asbs docs guides/cli/auto-registration --cat  # when create could not edit main.py
```

For the end-to-end workflow of a first project, read `asbs docs getting-started --cat`.

## Rules that bite

- **Only run `asbs setup` when no project exists.** Never scaffold over an existing project.
- **`asbs create` edits `src/main.py`.** If it reports that it could not, fix the registration by
  hand using `guides/cli/auto-registration`, and mind that **registration order matters**: services
  before the handlers, agents and APIs that resolve them.
- **Names are normalised, not rejected.** `order-placed`, `OrderPlaced` and `order_placed` all
  produce the same handler. Agent *namespaces* are the exception - see `blueprint-multi-agent`.
- After any `create`, run `asbs validate` before calling the work done. In a repository that
  hosts several agents, `asbs validate --group` checks the map and every agent it points at.
- **`asbs setup` has two modes.** `--group` writes the image's files (an empty agent map, the
  process settings, a group Dockerfile) and creates no agent. Without it, one agent is created
  in the current directory -- the same command whether it will run alone or in a group.
- **A scaffolded agent has no `agents.toml`**, deliberately: see `blueprint-multi-agent`.
