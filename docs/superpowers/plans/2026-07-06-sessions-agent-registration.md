# SessionsBus Agent Registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `SessionsBus` register with the sessions v0.4.0 dispatch registry before opening the SSE stream (and re-register on every reconnect, unregister on shutdown), fixing the 403 gate that breaks all deployed agents; also silence #44 keepalive log noise.

**Architecture:** Registration is a new pair of methods on `SessionsApiClient` (`register_agent`/`unregister_agent`), built on a new shared `_request` helper. `SessionsBus._connect_and_consume` calls `register_agent` before opening the stream so the reconnect/backoff loop retries registration for free. Job notifications are modelled as a `JobNotification` value object parsed once at the SSE boundary; the job-processing method is split into a thin dispatcher plus per-policy helpers with a single dispatch seam. `on_shutdown` drains in-flight jobs, then unregisters.

**Tech Stack:** Python 3.12+, httpx / httpx-sse, pydantic v2, pytest (async), OpenTelemetry. Line length 140. Quality gate: `black`, `ruff`, `mypy`.

**Spec:** `docs/superpowers/specs/2026-07-06-sessions-agent-registration-design.md`. Closes #45 and #44.

**Branch:** work on `feature/sessions-agent-registration` (already created). **All commits end with the repo's standard trailer** (`Co-Authored-By: Claude Opus 4.8 (1M context) …` + `Claude-Session: …`) — append it to every commit message; it is omitted from the command examples below only for brevity.

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `src/blueprint/agents/services/sessions/api_client.py` | HTTP client for the sessions REST API | Add `_request`, migrate 4 methods, add `register_agent`/`unregister_agent` |
| `src/blueprint/agents/models/sessions.py` | Sessions domain models | **Create** — `JobNotification` value object |
| `src/blueprint/agents/io/api/eventing/sessions_bus.py` | SSE consumer / job dispatcher | Register-before-connect, SSE event dispatch split, JobNotification threading, shutdown drain |
| `tests/unit/agents/services/sessions/conftest.py` | api_client test fixtures | Add `delete` to `mock_http_client` |
| `tests/unit/agents/services/sessions/test_api_client.py` | api_client unit tests | New tests for register/unregister |
| `tests/unit/agents/models/test_sessions.py` | model unit tests | **Create** |
| `tests/unit/agents/io/api/eventing/test_sessions_bus.py` | bus unit tests | New + updated tests |
| `CHANGELOG.md`, `docs/concepts/event-processing.md` | docs | Add entries |

---

## Task 1: `SessionsApiClient._request` helper + migrate existing methods (Refactor #1)

Behaviour-preserving extraction. The existing api_client tests are the regression guard — they must stay green **unchanged**.

**Files:**
- Modify: `src/blueprint/agents/services/sessions/api_client.py`
- Test: `tests/unit/agents/services/sessions/test_api_client.py` (existing, unchanged)

- [ ] **Step 1: Run the existing api_client tests to confirm the green baseline**

Run: `uv run pytest tests/unit/agents/services/sessions/test_api_client.py -v`
Expected: PASS (all existing tests).

- [ ] **Step 2: Add the `_request` helper**

Add this method to `SessionsApiClient` (place it just after `on_shutdown`). `Any` is already imported.

```python
async def _request(
    self,
    method: str,
    path: str,
    *,
    session_key: str | None = None,
    json: dict[str, Any] | None = None,
) -> httpx.Response:
    """Issue an authenticated request to the sessions service.

    Owns the client-initialised guard, URL assembly, and the optional
    X-Session-Key header. Returns the raw Response so callers decide how to treat
    status codes (registration branches on 404 rather than always raising).
    """
    if not self._client:
        raise ValueError("SessionsApiClient not initialized. Call on_startup() first.")

    url = f"{self._base_url}{path}"
    kwargs: dict[str, Any] = {}
    if session_key is not None:
        kwargs["headers"] = {"X-Session-Key": session_key}
    if json is not None:
        kwargs["json"] = json

    method_fn = getattr(self._client, method.lower())
    return await method_fn(url, **kwargs)
```

- [ ] **Step 3: Migrate `start_job` to use `_request`**

Replace the body of `start_job` (keep the signature and docstring) with:

```python
    logger.info("Starting job: session_id=%s, job_id=%s, agent_id=%s", session_id, job_id, agent_id)
    response = await self._request(
        "POST",
        f"/sessions/{session_id}/jobs/{job_id}/start",
        session_key=session_key,
        json={"agent_id": agent_id},
    )
    response.raise_for_status()
    job_data = response.json()
    logger.info("Job started successfully: job_id=%s", job_id)
    return job_data
```

- [ ] **Step 4: Migrate `get_job_detail` to use `_request`**

```python
    logger.debug("Fetching job detail: session_id=%s, job_id=%s", session_id, job_id)
    response = await self._request(
        "GET",
        f"/sessions/{session_id}/jobs/{job_id}",
        session_key=session_key,
    )
    response.raise_for_status()
    job_data = response.json()
    logger.debug("Job detail fetched: job_id=%s", job_id)
    return job_data
```

- [ ] **Step 5: Migrate `complete_job` to use `_request`**

```python
    logger.info("Completing job: session_id=%s, job_id=%s", session_id, job_id)
    response = await self._request(
        "POST",
        f"/sessions/{session_id}/jobs/{job_id}/complete",
        session_key=session_key,
        json={"result": result},
    )
    response.raise_for_status()
    job_data = response.json()
    logger.info("Job completed successfully: job_id=%s", job_id)
    return job_data
```

- [ ] **Step 6: Migrate `cancel_job` to use `_request`**

```python
    payload = {"reason": reason} if reason else {}
    logger.warning("Cancelling job: session_id=%s, job_id=%s, reason=%s", session_id, job_id, reason)
    response = await self._request(
        "POST",
        f"/sessions/{session_id}/jobs/{job_id}/cancel",
        session_key=session_key,
        json=payload,
    )
    response.raise_for_status()
    job_data = response.json()
    logger.info("Job cancelled successfully: job_id=%s", job_id)
    return job_data
```

- [ ] **Step 7: Run the existing tests to confirm they still pass**

Run: `uv run pytest tests/unit/agents/services/sessions/test_api_client.py -v`
Expected: PASS (unchanged) — `_request` dispatches to `client.post`/`client.get`, so the assertions on `.post`/`.get` call args still hold.

- [ ] **Step 8: Commit**

```bash
git add src/blueprint/agents/services/sessions/api_client.py
git commit -m "refactor(sessions): extract shared _request helper in SessionsApiClient"
```

---

## Task 2: `SessionsApiClient.register_agent` (#45)

**Files:**
- Modify: `src/blueprint/agents/services/sessions/api_client.py`
- Test: `tests/unit/agents/services/sessions/test_api_client.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_api_client.py`:

```python
import httpx


class TestRegisterAgent:
    async def test_posts_to_register_endpoint_with_body(self, started_api_client, mock_http_client) -> None:
        mock_http_client.post.return_value.status_code = 201
        await started_api_client.register_agent("agent-1", "analyser", ["classify"])
        url = mock_http_client.post.call_args[0][0]
        payload = mock_http_client.post.call_args[1]["json"]
        assert url.endswith("/agents/register")
        assert payload == {"agent_id": "agent-1", "agent_type": "analyser", "capabilities": ["classify"]}

    async def test_201_returns_true(self, started_api_client, mock_http_client) -> None:
        mock_http_client.post.return_value.status_code = 201
        assert await started_api_client.register_agent("a", "t", []) is True

    async def test_200_returns_true(self, started_api_client, mock_http_client) -> None:
        mock_http_client.post.return_value.status_code = 200
        assert await started_api_client.register_agent("a", "t", []) is True

    async def test_404_returns_false_and_does_not_raise(self, started_api_client, mock_http_client, caplog) -> None:
        mock_http_client.post.return_value.status_code = 404
        with caplog.at_level("WARNING"):
            result = await started_api_client.register_agent("a", "t", [])
        assert result is False
        assert "legacy" in caplog.text.lower()
        mock_http_client.post.return_value.raise_for_status.assert_not_called()

    async def test_500_raises_and_logs_body(self, started_api_client, mock_http_client, caplog) -> None:
        resp = mock_http_client.post.return_value
        resp.status_code = 500
        resp.text = "internal error detail"
        resp.raise_for_status.side_effect = httpx.HTTPStatusError("500", request=MagicMock(), response=resp)
        with caplog.at_level("ERROR"), pytest.raises(httpx.HTTPStatusError):
            await started_api_client.register_agent("a", "t", [])
        assert "internal error detail" in caplog.text

    async def test_optional_fields_included_when_given(self, started_api_client, mock_http_client) -> None:
        mock_http_client.post.return_value.status_code = 201
        await started_api_client.register_agent("a", "t", [], version="1.2.3", metadata={"k": "v"})
        payload = mock_http_client.post.call_args[1]["json"]
        assert payload["version"] == "1.2.3"
        assert payload["metadata"] == {"k": "v"}

    async def test_raises_when_not_initialized(self, api_client) -> None:
        with pytest.raises(ValueError, match="not initialized"):
            await api_client.register_agent("a", "t", [])
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/agents/services/sessions/test_api_client.py::TestRegisterAgent -v`
Expected: FAIL with `AttributeError: 'SessionsApiClient' object has no attribute 'register_agent'`.

- [ ] **Step 3: Implement `register_agent`**

Add to `SessionsApiClient` (after `cancel_job`):

```python
async def register_agent(
    self,
    agent_id: str,
    agent_type: str,
    capabilities: list[str],
    version: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Register the agent with the sessions dispatch registry (idempotent).

    v0.4.0 gates ``GET /jobs/stream/sse`` on a prior registration. Returns True
    when the server accepted it (200/201). Returns False when the server is a
    legacy (< v0.4.0) instance without the endpoint (404) — the caller may still
    open the stream. Raises on any other non-2xx so the reconnect loop backs off.
    """
    payload: dict[str, Any] = {"agent_id": agent_id, "agent_type": agent_type, "capabilities": capabilities}
    if version is not None:
        payload["version"] = version
    if metadata:
        payload["metadata"] = metadata

    response = await self._request("POST", "/agents/register", json=payload)

    if response.status_code == 404:
        logger.warning("Sessions service has no /agents/register (legacy < v0.4.0); proceeding without registration")
        return False

    if response.status_code >= 400:
        logger.error("Agent registration failed: status=%d body=%s", response.status_code, response.text)
    response.raise_for_status()
    logger.info("Agent registered: agent_id=%s (status=%d)", agent_id, response.status_code)
    return True
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/agents/services/sessions/test_api_client.py::TestRegisterAgent -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/blueprint/agents/services/sessions/api_client.py tests/unit/agents/services/sessions/test_api_client.py
git commit -m "feat(sessions): add SessionsApiClient.register_agent (#45)"
```

---

## Task 3: `SessionsApiClient.unregister_agent` (#45)

**Files:**
- Modify: `src/blueprint/agents/services/sessions/api_client.py`
- Modify: `tests/unit/agents/services/sessions/conftest.py`
- Test: `tests/unit/agents/services/sessions/test_api_client.py`

- [ ] **Step 1: Add `delete` to the `mock_http_client` fixture**

In `conftest.py`, inside `mock_http_client`, add after the `client.post` line:

```python
    client.delete = AsyncMock(return_value=mock_response)
```

- [ ] **Step 2: Write the failing tests**

Append to `test_api_client.py`:

```python
class TestUnregisterAgent:
    async def test_deletes_agent_endpoint(self, started_api_client, mock_http_client) -> None:
        mock_http_client.delete.return_value.status_code = 204
        await started_api_client.unregister_agent("agent-1")
        url = mock_http_client.delete.call_args[0][0]
        assert url.endswith("/agents/agent-1")

    async def test_swallows_errors(self, started_api_client, mock_http_client, caplog) -> None:
        mock_http_client.delete.side_effect = httpx.ConnectError("boom")
        with caplog.at_level("WARNING"):
            await started_api_client.unregister_agent("agent-1")  # must not raise
        assert "unregister failed" in caplog.text.lower()

    async def test_swallows_uninitialized_client(self, api_client) -> None:
        await api_client.unregister_agent("agent-1")  # must not raise
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/unit/agents/services/sessions/test_api_client.py::TestUnregisterAgent -v`
Expected: FAIL with `AttributeError: … has no attribute 'unregister_agent'`.

- [ ] **Step 4: Implement `unregister_agent`**

Add to `SessionsApiClient` (after `register_agent`):

```python
async def unregister_agent(self, agent_id: str) -> None:
    """Best-effort graceful deregistration (idempotent DELETE). Never raises.

    Called on shutdown; a failure here must not prevent a clean shutdown, so all
    exceptions (network error, 404 on legacy, closed client) are swallowed.
    """
    try:
        response = await self._request("DELETE", f"/agents/{agent_id}")
        logger.info("Agent unregistered: agent_id=%s (status=%d)", agent_id, response.status_code)
    except Exception as e:
        logger.warning("Graceful unregister failed for agent_id=%s: %s", agent_id, e)
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/unit/agents/services/sessions/test_api_client.py::TestUnregisterAgent -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/blueprint/agents/services/sessions/api_client.py tests/unit/agents/services/sessions/conftest.py tests/unit/agents/services/sessions/test_api_client.py
git commit -m "feat(sessions): add SessionsApiClient.unregister_agent (#45)"
```

---

## Task 4: `JobNotification` value object (Refactor #4 — model)

**Files:**
- Create: `src/blueprint/agents/models/sessions.py`
- Create: `tests/unit/agents/models/test_sessions.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/agents/models/test_sessions.py`:

```python
"""Unit tests for sessions domain models."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from blueprint.agents.models.sessions import JobNotification

_VALID = {
    "session_id": "00000000-0000-0000-0000-000000000001",
    "job_id": "00000000-0000-0000-0000-000000000002",
    "job_type": "transcription",
    "created_at": "2024-01-01T00:00:00Z",
}


class TestJobNotification:
    def test_parses_and_types_ids(self) -> None:
        n = JobNotification.model_validate(_VALID)
        assert n.session_id == UUID("00000000-0000-0000-0000-000000000001")
        assert n.job_id == UUID("00000000-0000-0000-0000-000000000002")
        assert n.job_type == "transcription"

    def test_created_at_optional(self) -> None:
        data = {k: v for k, v in _VALID.items() if k != "created_at"}
        assert JobNotification.model_validate(data).created_at is None

    def test_missing_required_field_raises(self) -> None:
        data = {k: v for k, v in _VALID.items() if k != "job_id"}
        with pytest.raises(ValidationError):
            JobNotification.model_validate(data)

    def test_extra_keys_preserved_in_payload(self) -> None:
        n = JobNotification.model_validate({**_VALID, "priority": "high"})
        payload = n.payload()
        assert payload["priority"] == "high"
        assert payload["session_id"] == _VALID["session_id"]  # UUID serialised back to str
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/agents/models/test_sessions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'blueprint.agents.models.sessions'`.

- [ ] **Step 3: Create the model**

Create `src/blueprint/agents/models/sessions.py`:

```python
"""Domain models for the sessions service integration."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class JobNotification(BaseModel):
    """A job dispatch notification received over the sessions SSE stream.

    Parsed once at the SSE boundary so field names and presence rules live in one
    place instead of being read ad hoc as ``dict`` keys throughout the bus. Extra
    keys in the payload are preserved (``extra="allow"``) and flow through to the
    CloudEvent ``data``.
    """

    model_config = ConfigDict(extra="allow")

    session_id: UUID
    job_id: UUID
    job_type: str
    created_at: str | None = None

    def payload(self) -> dict[str, Any]:
        """The full notification as a JSON-serialisable dict (UUIDs as strings)."""
        return self.model_dump(mode="json")
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/agents/models/test_sessions.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/blueprint/agents/models/sessions.py tests/unit/agents/models/test_sessions.py
git commit -m "feat(sessions): add JobNotification value object"
```

---

## Task 5: SessionsBus — register before opening the SSE stream (#45 core)

The headline fix, isolated in its own commit for reviewability and bisect. This inserts the register call at the top of `_connect_and_consume`; Task 6 later rewrites the rest of that method.

**Files:**
- Modify: `src/blueprint/agents/io/api/eventing/sessions_bus.py:155-169`
- Test: `tests/unit/agents/io/api/eventing/test_sessions_bus.py`

- [ ] **Step 1: Write the failing test**

Append to `test_sessions_bus.py` (inside a new class):

```python
class TestRegisterBeforeConnect:
    async def test_registers_before_opening_stream(self, started_sessions_bus: SessionsBus) -> None:
        bus = started_sessions_bus
        bus._base_url = "http://sessions-svc"
        bus._agent_id = "agent-001"
        bus._agent_type = "transcription"
        bus._capabilities = ["transcribe"]
        bus._api_key = "secret"
        bus._api_client.register_agent = AsyncMock(side_effect=RuntimeError("register-first"))

        with patch("blueprint.agents.io.api.eventing.sessions_bus.aconnect_sse") as mock_sse:
            with pytest.raises(RuntimeError, match="register-first"):
                await bus._connect_and_consume()
            mock_sse.assert_not_called()  # stream is never opened when registration fails

        bus._api_client.register_agent.assert_awaited_once_with(
            agent_id="agent-001", agent_type="transcription", capabilities=["transcribe"]
        )
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/agents/io/api/eventing/test_sessions_bus.py::TestRegisterBeforeConnect -v`
Expected: FAIL — `register_agent` is not called before `aconnect_sse` (the mock IS called / no register).

- [ ] **Step 3: Insert the register call at the top of `_connect_and_consume`**

In `_connect_and_consume`, immediately after the docstring and before `url = f"{self._base_url}/jobs/stream/sse"`, add:

```python
        # v0.4.0 gates the stream on registration — register (idempotent) before every
        # connect attempt. On a legacy server this is a no-op (404 -> False); on a hard
        # failure it raises and the reconnect loop (in _consume_sse_stream) backs off.
        await self._api_client.register_agent(
            agent_id=self._agent_id,
            agent_type=self._agent_type,
            capabilities=self._capabilities,
        )

```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/agents/io/api/eventing/test_sessions_bus.py::TestRegisterBeforeConnect -v`
Expected: PASS.

- [ ] **Step 5: Run the full bus test file (nothing else should regress)**

Run: `uv run pytest tests/unit/agents/io/api/eventing/test_sessions_bus.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/blueprint/agents/io/api/eventing/sessions_bus.py tests/unit/agents/io/api/eventing/test_sessions_bus.py
git commit -m "fix(sessions): register with dispatch registry before opening SSE stream (#45)"
```

---

## Task 6: SessionsBus — model notifications, split dispatch, keepalive + diagnostics (Refactors #2, #3, #4; #44)

One atomic commit because threading the `JobNotification` value object touches producer (`_connect_and_consume`) and consumers (`_handle_job_notification`, `_process_job_notification`, `_convert_to_cloud_event`) together — splitting them would leave a type-inconsistent intermediate commit. If the team decides to defer the `JobNotification` change to a follow-up PR (per the spec's scope guard), the `_dispatch_cloud_event` unification and error-policy extraction can still be kept; the notification would stay a dict.

**Files:**
- Modify: `src/blueprint/agents/io/api/eventing/sessions_bus.py` (imports, `__init__`, `_connect_and_consume`, new `_dispatch_sse_event`, `_handle_job_notification`, `_process_job_notification` + new helpers, `_convert_to_cloud_event`)
- Test: `tests/unit/agents/io/api/eventing/test_sessions_bus.py`

### Implementation

- [ ] **Step 1: Update imports**

At the top of `sessions_bus.py`, change the httpx_sse import and add the model import:

```python
from httpx_sse import ServerSentEvent, SSEError, aconnect_sse
```

Add with the other model imports:

```python
from ....models.sessions import JobNotification
```

- [ ] **Step 2: Track in-flight job tasks in `__init__`**

In `SessionsBus.__init__`, add after `self._shutdown_event: asyncio.Event = asyncio.Event()`:

```python
        # In-flight job tasks (tracked so shutdown can drain them, not orphan them)
        self._inflight_tasks: set[asyncio.Task[None]] = set()
```

- [ ] **Step 3: Rewrite `_connect_and_consume`**

Replace the whole method (from Task 5 it already has the register call at the top) with:

```python
    async def _connect_and_consume(self) -> None:
        """Register, then establish the SSE connection and consume events."""
        # v0.4.0 gates the stream on registration — register (idempotent) before every
        # connect attempt. On a legacy server this is a no-op (404 -> False); on a hard
        # failure it raises and the reconnect loop (in _consume_sse_stream) backs off.
        await self._api_client.register_agent(
            agent_id=self._agent_id,
            agent_type=self._agent_type,
            capabilities=self._capabilities,
        )

        url = f"{self._base_url}/jobs/stream/sse"
        params: dict[str, Any] = {"agent_id": self._agent_id}
        if self._agent_type:
            params["agent_type"] = self._agent_type
        if self._capabilities:
            params["capabilities"] = ",".join(self._capabilities)

        headers = {"X-Api-Key": self._api_key}

        async with httpx.AsyncClient(timeout=None) as client:
            async with aconnect_sse(client, "GET", url, params=params, headers=headers) as event_source:
                logger.info("SSE connection established")
                try:
                    async for sse in event_source.aiter_sse():
                        if self._shutdown_event.is_set():
                            break
                        self._dispatch_sse_event(sse)
                except SSEError:
                    # aconnect_sse hides the real status when the server returns JSON (e.g. a
                    # 403 dispatch-gate rejection). Surface status + body before backing off.
                    resp = event_source.response
                    body = (await resp.aread()).decode(errors="replace")[:500]
                    logger.error("SSE stream rejected: status=%d body=%s", resp.status_code, body)
                    raise
```

- [ ] **Step 4: Add `_dispatch_sse_event`**

Add this method directly after `_connect_and_consume`:

```python
    def _dispatch_sse_event(self, sse: ServerSentEvent) -> None:
        """Route a single SSE frame. Keepalive comment frames are ignored (#44)."""
        try:
            if sse.event == "connected":
                logger.info("SSE connected event received")

            elif sse.event == "job_created":
                notification = JobNotification.model_validate_json(sse.data)
                logger.info(
                    "Job notification received: job_id=%s, job_type=%s",
                    notification.job_id,
                    notification.job_type,
                )
                task = asyncio.create_task(self._handle_job_notification(notification))
                self._inflight_tasks.add(task)
                task.add_done_callback(self._inflight_tasks.discard)

            elif sse.event == "heartbeat":
                logger.debug("SSE heartbeat received")

            elif sse.event == "message" and not (sse.data or "").strip():
                # Server keepalive comment frame (`: keepalive`) surfaces as a default-type
                # `message` with empty data. Ignore it (#44) instead of warning every tick.
                logger.debug("SSE keepalive frame received")

            else:
                logger.warning("Unknown SSE event type: %s", sse.event)

        except Exception as e:
            logger.error("Error processing SSE event: %s", e, exc_info=True)
```

- [ ] **Step 5: Update `_handle_job_notification` signature**

Change the signature and the timeout log to take a `JobNotification`:

```python
    async def _handle_job_notification(self, notification: JobNotification) -> None:
        """Handle job notification with concurrency control.

        Args:
            notification: Parsed job notification from the SSE stream
        """
        if self._semaphore is None:
            raise RuntimeError("Semaphore not initialized")
        async with self._semaphore:
            try:
                await asyncio.wait_for(
                    self._process_job_notification(notification),
                    timeout=self._job_timeout,
                )
            except TimeoutError:
                logger.error(
                    "Job processing timeout after %ds: job_id=%s",
                    self._job_timeout,
                    notification.job_id,
                )
```

- [ ] **Step 6: Rewrite `_process_job_notification` as a thin dispatcher + add helpers**

Replace the whole `_process_job_notification` method with the following, and add the four helper methods after it:

```python
    async def _process_job_notification(self, notification: JobNotification) -> None:
        """Convert the notification to a CloudEvent and dispatch it, applying
        sessions-specific error handling. Each recovery policy lives in its own
        helper so this method stays a thin dispatcher.
        """
        session_id = notification.session_id
        job_id = notification.job_id
        job_type = notification.job_type

        with tracer.start_as_current_span("sessions_bus.process_job") as span:
            span.set_attribute("job_id", str(job_id))
            span.set_attribute("session_id", str(session_id))
            span.set_attribute("job_type", job_type)

            event = self._convert_to_cloud_event(notification)

            try:
                session_key = await self._require_key_provider().get_session_key(session_id)
                context = self._build_context(session_id, job_id, session_key)
                result = await self._dispatch_cloud_event(event, context)

                if result.status.value == "no_handler_found":
                    logger.warning("No handler found for job type %s (job_id=%s)", job_type, job_id)

            except InvalidEventError as e:
                await self._cancel_invalid_job(session_id, job_id, e)

            except RetryableHandlerError as e:
                logger.warning("Retryable error for job %s: %s. Job remains pending.", job_id, e)

            except httpx.HTTPStatusError as e:
                if e.response.status_code != 403:
                    raise
                await self._retry_with_fresh_key(event, session_id, job_id)

            except Exception as e:
                logger.exception("Unexpected error processing job %s: %s", job_id, e)

    def _require_key_provider(self) -> SessionKeyProvider:
        if self._key_provider is None:
            raise RuntimeError("SessionKeyProvider not initialized")
        return self._key_provider

    def _require_api_client(self) -> SessionsApiClient:
        if self._api_client is None:
            raise RuntimeError("SessionsApiClient not initialized")
        return self._api_client

    def _build_context(self, session_id: UUID, job_id: UUID, session_key: str) -> dict[str, Any]:
        return {
            "session_id": str(session_id),
            "job_id": str(job_id),
            "session_key": session_key,
            "sessions_api_client": self._api_client,
            "sessions_key_provider": self._key_provider,
        }

    async def _cancel_invalid_job(self, session_id: UUID, job_id: UUID, error: InvalidEventError) -> None:
        logger.error("Invalid job %s: %s. Cancelling.", job_id, error)
        try:
            session_key = await self._require_key_provider().get_session_key(session_id)
            await self._require_api_client().cancel_job(
                session_id=session_id,
                job_id=job_id,
                session_key=session_key,
                reason=f"Invalid event: {error}",
            )
        except Exception as cancel_error:
            logger.error("Failed to cancel job %s: %s", job_id, cancel_error)

    async def _retry_with_fresh_key(self, event: GenericCloudEvent, session_id: UUID, job_id: UUID) -> None:
        # A 403 from a handler means the cached session key is stale. Invalidate and retry
        # once through the SAME dispatch seam as the happy path (no separate code path).
        logger.error("Invalid session key for session %s", session_id)
        key_provider = self._require_key_provider()
        key_provider.invalidate_cache(session_id)
        try:
            session_key = await key_provider.get_session_key(session_id)
            context = self._build_context(session_id, job_id, session_key)
            await self._dispatch_cloud_event(event, context)
        except Exception as retry_error:
            logger.error("Retry failed for job %s: %s", job_id, retry_error)
            raise InvalidEventError(
                status="invalid_session_key",
                reason=f"Session key invalid: {retry_error}",
            ) from retry_error
```

- [ ] **Step 7: Update `_convert_to_cloud_event` to take a `JobNotification`**

Replace the whole method with:

```python
    def _convert_to_cloud_event(self, notification: JobNotification) -> GenericCloudEvent:
        """Convert a job notification to CloudEvent format.

        Args:
            notification: Parsed job notification

        Returns:
            GenericCloudEvent with the full job payload as ``data``
        """
        event_type = f"sessions.job.created.{notification.job_type}"
        kwargs: dict[str, Any] = {
            "specversion": "1.0",
            "id": str(notification.job_id),
            "type": event_type,
            "source": "/sessions-service",
            "subject": str(notification.session_id),
            "datacontenttype": "application/json",
            "data": notification.payload(),
        }
        # Only set `time` when present — GenericCloudEvent rejects a None time; omitting it
        # lets the model apply its default timestamp.
        if notification.created_at is not None:
            kwargs["time"] = notification.created_at
        return GenericCloudEvent(**kwargs)
```

### Tests

- [ ] **Step 8: Replace the `job_data` fixture usage with a `notification` fixture**

In `test_sessions_bus.py`, add near the other fixtures:

```python
from blueprint.agents.models.sessions import JobNotification


@pytest.fixture
def notification() -> JobNotification:
    return JobNotification(
        session_id=uuid4(),
        job_id=uuid4(),
        job_type="transcription",
        created_at="2024-01-01T00:00:00Z",
    )
```

- [ ] **Step 9: Update the existing `TestConvertToCloudEvent` tests to pass a `JobNotification`**

Replace the `TestConvertToCloudEvent` class body with:

```python
class TestConvertToCloudEvent:
    def _n(self, **overrides) -> JobNotification:
        base = {
            "session_id": uuid4(),
            "job_id": uuid4(),
            "job_type": "transcription",
            "created_at": "2024-01-01T00:00:00Z",
        }
        base.update(overrides)
        return JobNotification(**base)

    def test_event_type_includes_job_type(self, sessions_bus: SessionsBus) -> None:
        event = sessions_bus._convert_to_cloud_event(self._n(job_type="analysis"))
        assert event.type == "sessions.job.created.analysis"

    def test_event_id_is_job_id(self, sessions_bus: SessionsBus) -> None:
        job_id = uuid4()
        event = sessions_bus._convert_to_cloud_event(self._n(job_id=job_id))
        assert event.id == str(job_id)

    def test_subject_is_session_id(self, sessions_bus: SessionsBus) -> None:
        session_id = uuid4()
        event = sessions_bus._convert_to_cloud_event(self._n(session_id=session_id))
        assert event.subject == str(session_id)

    def test_source_is_sessions_service(self, sessions_bus: SessionsBus) -> None:
        event = sessions_bus._convert_to_cloud_event(self._n())
        assert event.source == "/sessions-service"

    def test_data_payload_contains_job_fields(self, sessions_bus: SessionsBus) -> None:
        n = self._n(job_type="analysis")
        event = sessions_bus._convert_to_cloud_event(n)
        assert event.data["job_type"] == "analysis"
        assert event.data["session_id"] == str(n.session_id)
```

- [ ] **Step 10: Update the existing `TestProcessJobNotification` tests to pass a `JobNotification`**

Replace every `job_data: dict` parameter with `notification: JobNotification` (the new fixture) and every `_process_job_notification(job_data)` call with `_process_job_notification(notification)`. Update the two id-based assertions to use `notification.job_id`. Also update the 403 test so the retry uses the unified dispatch seam:

```python
    async def test_403_invalidates_cache_and_retries(
        self, started_sessions_bus: SessionsBus, notification: JobNotification
    ) -> None:
        response_mock = MagicMock()
        response_mock.status_code = 403
        http_err = httpx.HTTPStatusError("403", request=MagicMock(), response=response_mock)
        processed = ProcessingResult(request_id="r", status=ProcessingStatus.PROCESSED)
        # First dispatch raises 403; the retry (same seam) succeeds.
        started_sessions_bus._dispatch_cloud_event = AsyncMock(side_effect=[http_err, processed])  # type: ignore[method-assign]

        await started_sessions_bus._process_job_notification(notification)

        started_sessions_bus._key_provider.invalidate_cache.assert_called_once()
        assert started_sessions_bus._dispatch_cloud_event.await_count == 2
```

And the retry-failure test (retry now goes through `_dispatch_cloud_event`):

```python
    async def test_403_retry_failure_propagates_invalid_event_error(
        self, started_sessions_bus: SessionsBus, notification: JobNotification
    ) -> None:
        response_mock = MagicMock()
        response_mock.status_code = 403
        http_err = httpx.HTTPStatusError("403", request=MagicMock(), response=response_mock)
        started_sessions_bus._dispatch_cloud_event = AsyncMock(  # type: ignore[method-assign]
            side_effect=[http_err, RuntimeError("still broken")]
        )
        with pytest.raises(InvalidEventError, match="Session key invalid"):
            await started_sessions_bus._process_job_notification(notification)
```

For `test_invalid_event_error_cancels_job`, update the assertion to `notification.job_id`:

```python
        assert call_kwargs["job_id"] == notification.job_id
```

- [ ] **Step 11: Add `_dispatch_sse_event` tests (keepalive #44, parsing, unknown)**

Append a new class:

```python
from types import SimpleNamespace


class TestDispatchSseEvent:
    def test_keepalive_message_frame_is_debug_not_warning(
        self, sessions_bus: SessionsBus, caplog: pytest.LogCaptureFixture
    ) -> None:
        sse = SimpleNamespace(event="message", data="")
        with caplog.at_level("DEBUG"):
            sessions_bus._dispatch_sse_event(sse)
        assert "keepalive" in caplog.text.lower()
        assert "Unknown SSE event type" not in caplog.text

    def test_named_unknown_event_with_payload_warns(
        self, sessions_bus: SessionsBus, caplog: pytest.LogCaptureFixture
    ) -> None:
        sse = SimpleNamespace(event="surprise", data="{}")
        with caplog.at_level("WARNING"):
            sessions_bus._dispatch_sse_event(sse)
        assert "Unknown SSE event type: surprise" in caplog.text

    def test_job_created_creates_tracked_task(self, started_sessions_bus: SessionsBus) -> None:
        started_sessions_bus._handle_job_notification = AsyncMock()  # type: ignore[method-assign]
        payload = '{"session_id": "00000000-0000-0000-0000-000000000001", ' \
                  '"job_id": "00000000-0000-0000-0000-000000000002", "job_type": "t"}'
        sse = SimpleNamespace(event="job_created", data=payload)
        started_sessions_bus._dispatch_sse_event(sse)
        assert len(started_sessions_bus._inflight_tasks) == 1

    def test_malformed_job_payload_is_logged_and_skipped(
        self, started_sessions_bus: SessionsBus, caplog: pytest.LogCaptureFixture
    ) -> None:
        sse = SimpleNamespace(event="job_created", data='{"missing": "ids"}')
        with caplog.at_level("ERROR"):
            started_sessions_bus._dispatch_sse_event(sse)
        assert "Error processing SSE event" in caplog.text
        assert len(started_sessions_bus._inflight_tasks) == 0
```

- [ ] **Step 12: Run the full bus test file**

Run: `uv run pytest tests/unit/agents/io/api/eventing/test_sessions_bus.py -v`
Expected: PASS. If `test_job_created_creates_tracked_task` warns about a pending task at teardown, that is acceptable (the AsyncMock coroutine is scheduled); the assertion runs synchronously before the loop yields.

- [ ] **Step 13: Commit**

```bash
git add src/blueprint/agents/io/api/eventing/sessions_bus.py tests/unit/agents/io/api/eventing/test_sessions_bus.py
git commit -m "refactor(sessions): model job notifications, split dispatch, ignore keepalive frames (#44)"
```

---

## Task 7: SessionsBus — drain in-flight jobs and unregister on shutdown (Refactor #5 + #45 shutdown)

**Files:**
- Modify: `src/blueprint/agents/io/api/eventing/sessions_bus.py` (`on_shutdown` + new `_drain_inflight_jobs`)
- Test: `tests/unit/agents/io/api/eventing/test_sessions_bus.py`

- [ ] **Step 1: Write the failing tests**

Append a new class:

```python
class TestShutdownDrainAndUnregister:
    async def test_unregisters_after_draining(self, started_sessions_bus: SessionsBus) -> None:
        bus = started_sessions_bus
        bus._agent_id = "agent-001"
        bus._api_client.unregister_agent = AsyncMock()

        async def _job() -> None:
            await asyncio.sleep(0.01)

        task = asyncio.create_task(_job())
        bus._inflight_tasks.add(task)
        task.add_done_callback(bus._inflight_tasks.discard)

        await bus.on_shutdown()

        assert task.done()
        bus._api_client.unregister_agent.assert_awaited_once_with("agent-001")

    async def test_drain_timeout_cancels_and_still_unregisters(self, started_sessions_bus: SessionsBus) -> None:
        bus = started_sessions_bus
        bus._agent_id = "agent-001"
        bus._job_timeout = 0  # force immediate drain timeout
        bus._api_client.unregister_agent = AsyncMock()

        async def _slow_job() -> None:
            await asyncio.sleep(10)

        task = asyncio.create_task(_slow_job())
        bus._inflight_tasks.add(task)
        task.add_done_callback(bus._inflight_tasks.discard)

        await bus.on_shutdown()

        assert task.cancelled()
        bus._api_client.unregister_agent.assert_awaited_once()

    async def test_unregister_failure_does_not_raise(self, started_sessions_bus: SessionsBus) -> None:
        bus = started_sessions_bus
        bus._agent_id = "agent-001"
        bus._api_client.unregister_agent = AsyncMock(side_effect=RuntimeError("boom"))
        # unregister_agent swallows internally, but guard shutdown even if it did not.
        await bus.on_shutdown()
```

> Note: `test_unregister_failure_does_not_raise` documents that shutdown is robust; `unregister_agent` already swallows its own errors (Task 3), so this asserts no exception escapes `on_shutdown`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/agents/io/api/eventing/test_sessions_bus.py::TestShutdownDrainAndUnregister -v`
Expected: FAIL — `on_shutdown` does not drain or call `unregister_agent`.

- [ ] **Step 3: Rewrite `on_shutdown` and add `_drain_inflight_jobs`**

Replace `on_shutdown` with:

```python
    async def on_shutdown(self) -> None:
        """Stop the stream, drain in-flight jobs, then unregister."""
        logger.info("SessionsBus closing...")

        self._shutdown_event.set()

        if self._sse_task and not self._sse_task.done():
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                logger.info("SSE task cancelled")

        await self._drain_inflight_jobs()

        if self._api_client is not None and self._agent_id:
            await self._api_client.unregister_agent(self._agent_id)

        logger.info("SessionsBus closed")

    async def _drain_inflight_jobs(self) -> None:
        """Wait for in-flight job tasks to finish (bounded by job_timeout), so we do
        not unregister or exit while a job is still reporting results. Tasks still
        running after the timeout are cancelled so shutdown cannot hang."""
        if not self._inflight_tasks:
            return
        pending = list(self._inflight_tasks)
        logger.info("Draining %d in-flight job(s) (timeout=%ds)", len(pending), self._job_timeout)
        try:
            await asyncio.wait_for(
                asyncio.gather(*pending, return_exceptions=True),
                timeout=self._job_timeout,
            )
        except TimeoutError:
            logger.warning("Drain timeout — cancelling %d in-flight job(s)", len(self._inflight_tasks))
            for task in list(self._inflight_tasks):
                task.cancel()
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/agents/io/api/eventing/test_sessions_bus.py::TestShutdownDrainAndUnregister -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/blueprint/agents/io/api/eventing/sessions_bus.py tests/unit/agents/io/api/eventing/test_sessions_bus.py
git commit -m "feat(sessions): drain in-flight jobs and unregister on shutdown (#45)"
```

---

## Task 8: Docs — CHANGELOG + event-processing concept

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/concepts/event-processing.md`

- [ ] **Step 1: Add the CHANGELOG entry**

Under the v0.7.0 (Unreleased) section — match the file's existing heading style; if there is a `### Fixed` subsection use it, otherwise add one — add:

```markdown
### Fixed
- `SessionsBus` now registers with the sessions dispatch registry (`POST /agents/register`) before
  opening the SSE job stream and re-registers on every reconnect, fixing the 403 gate introduced by
  sessions v0.4.0 that put all deployed agents into a reconnect loop (#45).
- Keepalive comment frames on the SSE stream are no longer logged as `Unknown SSE event type: message` (#44).

### Changed
- `SessionsBus` unregisters (`DELETE /agents/{agent_id}`) and drains in-flight jobs on graceful shutdown.
```

- [ ] **Step 2: Add a note to the event-processing concept doc**

In `docs/concepts/event-processing.md`, find the section describing the sessions SSE flow (search for `SessionsBus` or `stream/sse`) and add a short paragraph:

```markdown
> **Agent registration (sessions v0.4.0+):** Before opening the SSE job stream, `SessionsBus` calls
> `POST /agents/register` to declare its `agent_id`, `agent_type`, and `capabilities` — the dispatch
> source of truth. It re-registers before every reconnect attempt (idempotent) and unregisters
> (`DELETE /agents/{agent_id}`) on graceful shutdown. Against a pre-v0.4.0 server the register call
> returns 404 and is skipped.
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md docs/concepts/event-processing.md
git commit -m "docs(sessions): document agent registration flow (#45, #44)"
```

---

## Task 9: Final verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full unit + offline test suite**

Run: `uv run pytest tests/ -m "not integration"`
Expected: PASS, no failures. In particular `tests/integration/test_sessions_startup_resilience.py::test_app_starts_when_sessions_service_unreachable` (offline, not marked integration) must still pass — register failure happens inside the SSE task and must not block startup.

- [ ] **Step 2: Run the quality gate**

Run: `black src/ tests/ && ruff check src/ tests/ && mypy src/`
Expected: all clean. Fix any findings in the touched files only.

- [ ] **Step 3: Confirm the commit series is coherent**

Run: `git log --oneline develop..HEAD`
Expected: the docs/spec commits plus Tasks 1–8 as separate, well-scoped commits.

- [ ] **Step 4 (optional): open the PR**

Only if the user asks. Target `develop` (protected — PR only, human review required). Suggested title: `fix(sessions): register with dispatch registry before opening SSE stream (#45, #44)`. Reference the spec and both issues in the body.

---

## Self-Review

- **Spec coverage:** register-before-connect (Task 5/6), re-register per reconnect (Task 6 — call is inside `_connect_and_consume`, which the reconnect loop re-invokes), 404 legacy handling (Task 2), surface 403 body (Task 2 register + Task 6 SSE wrap), keepalive #44 (Task 6), unregister on shutdown (Task 7), `_request` helper #1 (Task 1), single dispatch seam #2 (Task 6 `_retry_with_fresh_key`), error-policy extraction #3 (Task 6), `JobNotification` #4 (Tasks 4, 6), shutdown drain #5 (Task 7), config unchanged (no task needed), docs (Task 8), integration resilience preserved (Task 9). All spec sections map to a task.
- **Placeholder scan:** none — every code and test step contains complete code.
- **Type consistency:** `register_agent(agent_id, agent_type, capabilities, version=None, metadata=None) -> bool` and `unregister_agent(agent_id) -> None` used identically in Tasks 2/3/5/6/7. `JobNotification(session_id, job_id, job_type, created_at)` + `.payload()` used consistently in Tasks 4/6. `_dispatch_cloud_event`, `_convert_to_cloud_event(notification)`, `_build_context`, `_require_key_provider`, `_require_api_client` names are consistent across steps.
