# CLI Reference

The `asbs` command-line tool is the primary interface for scaffolding, developing, and managing
Blueprint Agents projects. It is installed automatically with the `avs-blueprint-agents` package.

```bash
pip install avs-blueprint-agents
```

This page is an index. Each command has its own page so you can read only the part you need.

---

## Commands

| Command | Page | What it does |
|---|---|---|
| `asbs setup` | [setup](cli/setup.md) | Scaffold a complete new project |
| `asbs create` | [create](cli/create.md) | Add a handler, service, api, agent or scheduler |
| `asbs validate` | [validate](cli/validate.md) | Check project structure and configuration |
| `asbs dev` | [dev](cli/dev.md) | Run the development server with reload |
| `asbs claude` | [claude](cli/claude.md) | Copy the Claude Code resources into a project |

---

## Behaviour shared by every command

| Topic | Page | Why you would read it |
|---|---|---|
| Naming conventions | [naming](cli/naming.md) | How the name you type becomes a class, a file and a runtime name |
| Auto-registration troubleshooting | [auto-registration](cli/auto-registration.md) | `asbs create` could not edit `src/main.py`, and what to do about it |

---

## Quick reference

```bash
asbs setup <project_name>                          # Scaffold complete project
asbs create handler <name> [--event-type TYPE]     # Add EventHandler
asbs create service <name>                         # Add Service
asbs create api <name>                             # Add RestApi
asbs create agent <name>                           # Add AgentRuntime
asbs create scheduler <name> [--cron CRON]         # Add Scheduler
asbs validate                                      # Validate project structure
asbs dev [--port 8000]                             # Run dev server
asbs claude [--overwrite]                          # Install Claude Code resources
```
