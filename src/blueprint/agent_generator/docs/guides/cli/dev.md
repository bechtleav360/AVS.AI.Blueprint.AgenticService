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

---

## Running a single agent

An agent directory carries no `agents.toml`, so there is nothing there to name it. `asbs dev`
supplies the name instead -- from `--name`, or the directory's own name:

```bash
cd agents/some_topic/my_agent
asbs dev                    # serves it as "my_agent"
asbs dev --name orders      # serves it as "orders"
```

The map it needs is written outside the project for that run and removed afterwards. Nothing is
created in the agent's directory: an `agents.toml` left behind there is exactly the file an
agent must not carry.

The name decides the route prefix, so `/api/my_agent/...` here and `/api/<map key>/...` in a
group image. If they differ, development and production differ -- `asbs validate --group` says
so when a map key does not match its directory name.

Where an `agents.toml` *is* present -- an image's directory -- `asbs dev` hosts the agents it
names, as before.
