# asbs dev

Run this project's agents in development mode with hot reload, **under the namespaces they are
deployed under**. A development server at the root namespace would serve `/api/orders/{id}` where
production serves `/api/order/orders/{id}`, and would consume under a different queue group, so
every local URL and every local integration test would differ from the deployed one.

With an `agents.toml`, it serves the group through
`uvicorn blueprint.agents.entrypoint:create_group_app --factory --reload`. Without one -- a project
written before the agent map, which builds its own application -- it serves `src.main:app` exactly
as it always did.

```bash
asbs dev [--agents <a,b>] [--host <host>] [--port <port>]
```

## Options

| Flag               | Description                                                 | Default          |
|--------------------|-------------------------------------------------------------|------------------|
| `--agents <a,b>`   | Comma-separated agents to host                              | every agent in `agents.toml` |
| `--host <host>`    | Host to bind the server to                                  | `127.0.0.1`      |
| `--port <port>`    | Port to bind the server to                                  | `8000`           |

`BLUEPRINT_GROUP` or `BLUEPRINT_AGENTS` already set in the environment always wins: a developer
reproducing a particular deployment is not overridden by a default read out of the agent map.

## Example

```bash
asbs dev --port 9000
```

```
INFO:     Blueprint Agents dev server starting...
INFO:     Uvicorn running on http://0.0.0.0:9000 (Press CTRL+C to quit)
INFO:     Started reloader process
```

The development server watches for file changes in the `src/` directory and automatically restarts when modifications are detected.
