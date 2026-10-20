# asbs dev

Run this project's agents in development mode with hot reload. What it serves depends on the
directory it is run in:

- **An image directory** (one with an `agents.toml`): the agents the map names, under their
  namespaces, through `uvicorn blueprint.agents.entrypoint:create_group_app --factory --reload` --
  the routes and queue groups a grouped deployment has.
- **An agent directory** (no `agents.toml`): the agent alone, at the root namespace, through
  `uvicorn src.main:create_app --factory --reload` -- as its own Dockerfile serves it -- unless
  `--name` gives it the namespace a group image would (see
  [Running a single agent](#running-a-single-agent)). A project from before the declaration split,
  whose `src/main.py` builds its own `app` and defines no `create_app`, is served as
  `src.main:app`, as it always was.

```bash
asbs dev [--name <agent>] [--agents <a,b>] [--host <host>] [--port <port>]
```

## Options

| Flag               | Description                                                 | Default          |
|--------------------|-------------------------------------------------------------|------------------|
| `--name <agent>`   | Serve the agent in this directory under that name, as a group image would | served on its own, at the root |
| `--agents <a,b>`   | Comma-separated agents to host, in an image directory       | every agent in `agents.toml` |
| `--host <host>`    | Host to bind the server to                                  | `127.0.0.1`      |
| `--port <port>`    | Port to bind the server to                                  | `8000`           |

`BLUEPRINT_GROUP` or `BLUEPRINT_AGENTS` already set in the environment always wins over the map
and `--agents`: a developer reproducing a particular deployment is not overridden by a default
read out of the agent map.

## Example

```bash
asbs dev --port 9000
```

In an agent directory:

```
Serving this agent on its own (src.main:create_app), at the root namespace.
Use --name <agent> to serve it under the namespace a group image would give it.
Starting development server on 127.0.0.1:9000
Press Ctrl+C to stop

INFO:     Uvicorn running on http://127.0.0.1:9000 (Press CTRL+C to quit)
INFO:     Started reloader process [...]
```

uvicorn's reloader watches the directory `asbs dev` was started in and restarts the server when a
file changes.

---

## Running a single agent

An agent directory carries no `agents.toml`, so there is nothing there to name it. Without
`--name`, `asbs dev` serves the agent on its own, at the root namespace, as its own Dockerfile
does; `--name` serves it under that name, as a group image would:

```bash
cd agents/some_topic/my_agent
asbs dev                    # served on its own: routes under /api/...
asbs dev --name orders      # served as "orders": routes under /api/orders/...
```

With `--name`, the map it needs is written outside the project for that run and removed afterwards. Nothing is
created in the agent's directory: an `agents.toml` left behind there is exactly the file an
agent must not carry.

The name decides the route prefix, so pass the agent's map key as `--name` to develop against the
routes of the group image (`/api/<map key>/...`).

Where an `agents.toml` *is* present -- an image's directory -- `asbs dev` hosts the agents it
names, as before.
