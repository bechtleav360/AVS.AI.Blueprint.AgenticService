# Integration Test Prompt Template

This document is no longer a step-by-step guide. Instead, it provides a ready-made **prompt** you can paste into another LLM so it can generate the reusable integration-test suite exactly the way this project requires (blackbox testing through the public Dapr API, with only external dependencies mocked).

---

## How to Use This Template

1. Read the assumptions below so you know what the prompt covers.
2. Copy the entire prompt block (everything between the ```text fences) and provide it to the target LLM verbatim.
3. If you need to adjust handler names, endpoints, or mock targets, edit the prompt text **before** sending it.
4. Expect the LLM to return two files:
   - `tests/integration/conftest.py`
   - `tests/integration/test_event_processing.py`
5. Review the LLM output, run `pytest tests/integration -v`, and iterate if necessary.

---

## Prompt (copy everything between the fences)

```text
You are an expert Python engineer specializing in FastAPI, Dapr, pytest, and blackbox systems testing. Create the integration-test scaffolding for the Agents Blueprint project so the tests exercise the public API exactly as production does—no internal hooks, no partial mocks of framework classes.

PROJECT CONTEXT
- The service exposes FastAPI endpoints, including `/events/{topic}` (Dapr event ingress) and `/dapr/subscribe` (subscription discovery).
- Events are CloudEvents processed by blueprint agent handlers built via `AppBuilder`.
- Downstream publications go through Dapr’s HTTP publish API (e.g., `POST http://localhost:3500/v1.0/publish/pubsub/<event>`), which we fake using `respx`.
- Only external services (databases, vendor APIs, LLMs, etc.) may be mocked via `unittest.mock.patch`. Internal classes like `ProcessingService`, `EventHandler`, `ComponentRegistry`, etc., must remain untouched.

TESTING GOALS (must ALL be covered)
1. Verify the FastAPI app starts without errors by hitting `/health` (200 or 404 acceptable).
2. Confirm `/dapr/subscribe` returns a list of subscriptions.
3. Send CloudEvents (and plain JSON payloads that get wrapped) to `/events/invoice.submitted` and assert the handler chain produces downstream events.
4. Use `respx` to intercept the HTTP publish call to `http://localhost:3500/v1.0/publish/pubsub/<event>` and assert payload + call count.
5. Demonstrate mocking of external dependencies only (vendor API, database lookup, LLM call) while keeping the rest of the system blackbox.
6. Cover multiple events in sequence to ensure repeatability.
7. Show how to inspect the published payload for data integrity.

STRICT REQUIREMENTS
- Follow object-oriented style: define handlers via classes (e.g., `InvoiceAnalysisHandler` extending `EventHandler`).
- Build the app exactly as `main.py` would (via `AppBuilder` + config) in fixtures.
- Use pytest fixtures for config, app, `TestClient`, and each external mock.
- Use `respx.mock()` context managers inside tests (not global patches).
- When mocking external services, show realistic return values (IDs, vendor info, approvals, etc.).
- Provide informative docstrings/comments only when they clarify non-obvious logic.
- Respect the dependency set (`pytest`, `pytest-asyncio`, `respx`, `httpx`).

DELIVERABLES
1. `tests/integration/conftest.py`
   - Fixtures: `config`, `app`, `client`, `mock_external_api`, `mock_database`, `mock_llm_service`.
   - `config` uses `Config` with `root_path=Path(__file__).parent.parent.parent` and empty `settings_files`.
   - `app` builds the FastAPI app via `AppBuilder`.
   - Each mock fixture uses `patch()` with realistic targets (e.g., `your_project.services.vendor_service.lookup`).

2. `tests/integration/test_event_processing.py`
   - Top-level docstring summarizing purpose.
   - Imports: `json`, `uuid4`, `pytest`, `respx`, `MagicMock`, `patch`, FastAPI/blueprint components.
   - Define `InvoiceAnalysisHandler(EventHandler)` as the concrete example handler (priority 10, handles `invoice.submitted`, emits `invoice.analyzed`).
   - Fixture `app_with_handlers` ensures handlers are registered (if registry interaction needed, describe succinctly).
   - `TestEventProcessing` class containing the following tests (all async-safe, but may use regular pytest since TestClient is sync):
     a. `test_app_starts_without_errors`
     b. `test_dapr_subscribe_endpoint_exists`
     c. `test_event_received_via_dapr_endpoint` (send CloudEvent, assert SUCCESS, assert `respx` publish called)
     d. `test_event_published_via_respx` (verify payload content + call count)
     e. `test_event_with_mocked_external_service` (vendor lookup mock)
     f. `test_event_with_plain_json_payload` (plain JSON auto-wrapped)
     g. `test_multiple_events_in_sequence` (loop 3 events, assert publish count)
     h. Additional focused tests demonstrating mocked database + LLM services and verifying they were called.
   - Every test must stay blackbox: only interact via HTTP requests and mocked external boundaries.

CODING CHECKLIST FOR THE LLM
- [ ] Add necessary imports (pytest, respx, MagicMock, patch, TestClient, blueprint modules).
- [ ] Ensure fixtures and tests are deterministic (no random sleeps, no real network calls).
- [ ] Use `with respx.mock:` inside each test needing publish verification.
- [ ] Use `uuid4()` for CloudEvent IDs.
- [ ] Validate HTTP status codes and JSON structure from responses.
- [ ] Assert that mocked external services were called as expected.
- [ ] Provide `pytest` markers only if required (not necessary otherwise).
- [ ] Keep assertions tight and specific.

OUTPUT FORMAT
- Return the final answer as Markdown with two fenced code blocks: one for `tests/integration/conftest.py`, one for `tests/integration/test_event_processing.py`.
- Precede the code with a succinct summary of what was generated.
- Do not include instructions or reasoning in the generated files—only the code with minimal docstrings/comments.

REMINDERS
- Never mock or patch internal framework classes.
- Never call handlers or processing services directly—go through the FastAPI client.
- Keep tests fast and side-effect free.
- Use `respx` + `MagicMock(status_code=204)` to emulate Dapr publish success.

Your response to this prompt must satisfy every requirement above.
