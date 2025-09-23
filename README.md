This is the root documentation for the Agents Blueprint.

For details, see:

- Getting started and running the app: [`start.sh`](./start.sh)
- Runtime entrypoint: `agent/src/main.py`
- Custom agent implementation: `agent/src/custom/agent/runtime.py`
- Tools and deterministic logic: `agent/src/custom/agent/tools.py`, `agent/src/custom/agent/logic.py`
- Prompts (system and variants): `agent/src/custom/prompts/`
- Custom models (context, result, resource): `agent/src/custom/models/`
- Framework (base, do not modify): `base/src/`
- Docker/Compose setup: `agent/Dockerfile`, `docker-compose.yml`
- Observability (Jaeger): open `http://localhost:16686`
- API docs: open `http://localhost:8000/docs`

Contributing & Policies:
- Contributing guide: `agent/CONTRIBUTING.md`

## Getting Started: Build a Custom Agent in 6 Steps

1) Create your system prompt
- Path: `agent/src/custom/prompts/system.prompt`
- Keep it concise. Example:
```
You are a helpful agent. Prefer calling tools for deterministic checks and return structured results.
```

2) Define your processing context (deps)
- Path: `agent/src/custom/models/processing.py` (already provided: `ProcessingContext`)
- Add any fields you need (e.g., user, tenant, correlation IDs). The base builds this from `process_request(**kwargs)`.

3) Add a typed tool (deterministic logic)
- Path: `agent/src/custom/agent/tools.py`
- Use typed inputs/outputs so the tool schema is clear (see `ResourceInput`, `CustomAgentOutput`).
- Example tool: `Tools.analyze_resource(ctx: RunContext[ProcessingContext], resource: ResourceInput) -> CustomAgentOutput`

4) Wire your tool(s) into the runtime
- Path: `agent/src/custom/agent/runtime.py`
- Ensure `_get_tools()` returns your tool methods, e.g. `return [tools.analyze_resource]`.
- Ensure `_get_prompt_name()` returns the prompt filename (default: `system`).
- Ensure `_get_result_type()` returns your output model (default overridden to `CustomAgentOutput`).

5) Run the agent
- Start locally:
```bash
./start.sh
# or
docker-compose up --build
```
- Open API docs: http://localhost:8000/docs
- Open Jaeger: http://localhost:16686

6) (Optional) Extend events or REST
- Base provides generic endpoints (`/api`, `/events`, `/dapr/subscribe`).
- To add custom routes, create routers under `agent/src/custom/api/` and include them in `agent/src/main.py`.

Notes
- Base handles tracing, prompt loading, and context building. Implementations call the model via `await self.run_with_agent(prompt, deps=context)` and return typed outputs.
- Do not modify `base/`; put all custom code under `agent/src/custom/`.
- Pre-commit policy (no edits in `base/`): see `.git/hooks/pre-commit`