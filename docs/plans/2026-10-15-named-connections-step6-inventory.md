# Named connections, step 6 -- inventory

Acceptance record for step 6 of `2026-10-14-named-connections.md`: every place checked, what was
changed or why nothing was, and what is still open. Checked against the code on
`feature/multi-agent-namespaces` (2026-10-15). "Read" = compared with the code; "run" = executed.

## Changed

| Place | Finding | Change |
|---|---|---|
| `agent_generator/claude_docs/CLAUDE.md` | built `AgentRuntime` + `AppBuilder(config).build()` in "Wiring" (W1); handler example with two-step logic; no handler rules | template declaration with `create_app()`; rules 7-10 (routing on the envelope, one service call, relevance in the service, no LLM in handlers, no run state on `self`); `HandlerResult.skipped`; `context["runtime"]` (W9); `models/` split (W11) |
| `claude_docs/agents/blueprint-builder.md` | scheduler without `super().on_startup()` (W4); built `AgentBuilder(config)...build(name=)` (W1) | fixed; handler pattern and rules 9 and 13 |
| `claude_docs/agents/blueprint-architect.md` | no rule on service entry points or LLM placement | two rules added |
| `claude_docs/skills/blueprint-events`, `add-component` | `None` described as "not mine, or nothing to publish"; handler/agent/scheduler guidance | return values incl. `skipped`; handler rules; scheduler `super()` |
| `base_files/src/handlers/handler.txt` | "This is where the main business logic is implemented" (W7); idempotency comment asks for logic in the handler (W8) | docstrings and comment put the decision in the service |
| `docs/components/event-handlers.md` | `HandlerResult` "does not stop subsequent handlers" (W2); tenant example in the context-key section; instance registration | chain semantics table; context keys per D10 incl. `nats_connection`; classes only; full example with DTO and `skipped` |
| `docs/concepts/event-processing.md` | sync `can_handle_event(event)`, `priority = 1`, "any other value is available to the next handler" | rewritten against `_dispatch`; table per return value |
| `docs/concepts/architecture.md` | `with_agent("name", Cls)`, `register_routes`, `execute()`, `priority = 10` (W3) | rewritten; startup order checked against `app_builder.py:1648-1684` (unchanged, correct) |
| `docs/components/agents.md`, `rest-apis.md`, `schedulers.md`, `services.md`, `concepts/caching.md`, `concepts/configuration.md`, `getting-started.md` | `AppBuilder(config)...build()`, instances, `.with_config()`/`.with_api()`/`with_name()` (W1); wrong import paths in `agents.md` | declaration form; imports fixed |
| `docs/reference/api.md` | `AppBuilder(config: Config)`, `AgentBuilder(config, ...)` required | optional config, `build(config=None)` for both |
| `docs/reference/models.md`, `concepts/observability.md` | -- | `skip_reason`, `ProcessingStatus.SKIPPED`, `blueprint.events.skipped` |
| `docs/reference/configuration-keys.md` | `nats_subscriptions`, `nats_publish_mode`, `nats_publish_subjects` read by the code, documented nowhere | rows added; every other `nats_*` key in the code is present (diffed) |
| `docs/guides/deployment.md` | "never exercised against a real broker"; ack_wait rule ignored the heartbeat | banner states what `tests/integration` covers; skipped/timeout dispositions; heartbeat |
| `docs/guides/testing.md` | `api.register_routes(app.router)` -- no such method | `app.include_router(api.router)` |
| `docs/specs/2026-08-28-multi-agent-grouping.md` | sec. 5.2 defaults 300 / 16 / 5 the code does not apply; sec. 7.3 without the heartbeat | corrected; new keys listed; sec. 7.2 gains the skip |
| `README.md` | -- (already the declaration) | feature line for concurrency / named connections; component table |
| `examples/*/src/main.py` + READMEs | module-level `app = AppBuilder(config)...build()`, instances | declaration + `create_app()`; `uvicorn src.main:create_app --factory` |
| `asbs validate` | no check of the new keys | `_nats_findings` (step-6 item "asbs validate checks for the new keys") |

## Checked, unchanged

- **W5**: already fixed by `9b4560c` (the second `CLAUDE.md` was removed).
- `AGENTS.md`, `CLAUDE.md` (repository): no statement about delivery, handlers or `main.py` that
  disagrees with the code.
- `docs/guides/multi-agent-setup.md`, `multi-agent-migration.md`: already show the declaration;
  the migration guide shows the old form deliberately as "before".
- `claude_docs/skills/blueprint-config`, `-deployment`, `-multi-agent`, `-troubleshooting`,
  `-testing`, `-cli`, `-migration`, `new-agent-service`: grepped for main.py patterns, chain
  semantics and NATS delivery claims; nothing found that disagrees. Not read line by line.

## Run

- Unit suite: 3588 passed, 1 skipped (was 3553 before step 6).
- `tests/integration/test_skipped_result.py` + `test_event_path.py` against `nats:2.10-alpine`
  (throwaway container, port 14222): 8 passed. Control on the unchanged code: a `None` from the only
  handler logs "No handler processed event" at WARNING.
- `asbs setup` + `asbs create handler` + `asbs validate` on a scratch project: the scaffold carries
  the new handler docstrings, validates clean, and `nats_max_concurrent_runs = 0` is reported.
- Every example started once (`uvicorn src.main:create_app --factory`, Windows host, NATS in WSL
  Docker): `/health/live` 200 for all five; `/health/ready` 200 for `inventory_api`,
  `health_monitor` and `webhook_relay` (connected to the broker); 503 for `order_event_pipeline`
  (no Dapr sidecar) and `document_summarizer` (no model key) -- both expected. Each example's own
  tests and `tests/unit/examples`: green.
- Grep for removed APIs (`with_config(`, `with_api(`, `with_prompt_file`, `register_routes(`,
  `with_agent("name", Cls)`, `AgentBuilder(config` in docs): only plans and changelogs remain.

## Done after the first pass (2026-10-15)

- `webhook_relay` and `order_event_pipeline`: one handler per event type, one service call
  (`f72c84a`, `1d40fdc`); `document_summarizer` without `assert` (`4cbc3c2`).
- The named-connection example `examples/site_readings` (`30f14e7`), run live against a broker with
  accounts.
- Spec sec. 7.2 now matches the WARNING for an event no handler takes (`ad771f0`, own commit).
- `nats_delivery_attempt` / `nats_max_deliver` in the handler context (`b7586e3`).

## Open

- **Model file names differ:** the template scaffolds `dto.py` / `domain_models.py` / `mapper.py`;
  the examples use `schemas.py` (+ `domain.py` where there are handlers). `document_summarizer`,
  `health_monitor` and `inventory_api` have no handlers and keep one `schemas.py`; their APIs pass
  request DTOs to the service.
- **Pre-existing integration failure:** `test_acknowledgement_lifecycle.py::TestARetryableFailureComesBack::test_the_broker_counts_it_as_a_redelivery`
  fails on the unchanged code too (control run 2026-10-15).
- **Not checked:** the untracked specs `2026-09-23-dynamic-subscriptions.md`,
  `2026-09-24-handler-time-bounds.md` (sec. 4.5) and `2026-09-25-config-key-registry.md` (not in the
  repository); ADRs (owned outside the repository); `asbs docs` output beyond the files above.
- The examples were started on the Windows host against brokers in WSL Docker, not inside WSL.
