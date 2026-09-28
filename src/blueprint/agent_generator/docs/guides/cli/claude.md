# asbs claude

Copy the framework's Claude Code resources into a project, so that Claude Code picks up the
Blueprint patterns when working in it.

```bash
asbs claude [<project-dir>] [--overwrite] [--verbose]
```

## Arguments

| Argument        | Description                          | Default |
|-----------------|--------------------------------------|---------|
| `project-dir`   | Project root to write into           | `.`     |

## Options

| Flag              | Description                                         | Default |
|-------------------|-----------------------------------------------------|---------|
| `--overwrite`     | Replace files that already exist                    | off     |
| `--verbose`, `-v` | Debug-level logging                                 | off     |

There are no `create` / `update` subcommands: the command is idempotent, and `--overwrite` is the
difference between leaving existing files alone and replacing them.

## What it copies

| From the framework | To the project | Contents |
|---|---|---|
| `claude_docs/CLAUDE.md` | `src/CLAUDE.md` | Framework reference: base classes, the registry and lifecycle rules, component patterns, configuration |
| `claude_docs/agents/` | `.claude/agents/` | Architecture agents |
| `claude_docs/skills/` | `.claude/skills/` | CLI skills |

Nothing here is generated from *your* project: the files are the framework's own documentation,
copied. They are not updated when you run `asbs create`.

## Example

```bash
asbs claude
asbs claude --overwrite    # after upgrading the framework
```

## Project-Specific CLAUDE.md

You can optionally create a `CLAUDE.md` file in your project root for project-specific context:

```markdown
# My Service - Blueprint Agents Project

## Overview
Brief description of this service's purpose and architecture.

## Key Components
- **OrderService**: Validates and processes orders
- **OrderHandler**: Responds to order.placed events
- **OrderApi**: REST endpoints for order management

## Deployment
Information specific to how this service is deployed.

## Team Guidelines
Any team-specific development guidelines or patterns.
```

This user-created file is not updated by `asbs` commands.
