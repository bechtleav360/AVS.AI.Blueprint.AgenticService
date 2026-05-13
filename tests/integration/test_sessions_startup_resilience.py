"""Integration test: AppBuilder.build() with event_bus='sessions' yields a
FastAPI app whose lifespan completes even when the sessions service URL is
unreachable. Standard REST endpoints (the framework root API) must respond.
"""

import logging
import socket
import threading

import pytest
from fastapi.testclient import TestClient

from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.component.component import Component
from blueprint.agents.config import Config
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent


def _closed_port() -> int:
    """Bind and immediately close a socket to obtain a port that will refuse connections.

    Guarantees ECONNREFUSED (not timeout) on the next connection attempt across all
    platforms — unlike hardcoded low ports which may behave inconsistently under CI
    networking constraints.
    """
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# SessionsBus.on_startup spawns the SSE consumer as an asyncio task and returns
# without awaiting any TCP I/O. Lifespan completion therefore does not depend on
# the connection succeeding; it depends only on on_startup itself being awaited
# without raising. 5s is generous for that work on a loaded CI runner.
_LIFESPAN_TIMEOUT_SECONDS = 5


class _NullHandler(EventHandlerBase):
    """Minimal handler so build() takes the eventing branch."""

    async def on_startup(self) -> None:  # pragma: no cover - trivial
        return None

    async def on_shutdown(self) -> None:  # pragma: no cover - trivial
        return None

    async def can_handle_event(self, event: GenericCloudEvent, context: dict) -> bool:
        return False

    async def handle_event(self, event: GenericCloudEvent, context: dict):  # pragma: no cover
        return None


@pytest.fixture(autouse=True)
def _reset_component_state():
    Component.shared_config = None
    Component.shared_registry = None
    yield
    Component.shared_config = None
    Component.shared_registry = None


# Not marked @pytest.mark.integration — this test is fully offline (it deliberately
# targets a closed local port) and must run in the offline CI matrix.
def test_app_starts_when_sessions_service_unreachable(tmp_path, monkeypatch, caplog):
    """With sessions URL pointed at a closed port, build() returns and
    TestClient can hit the root endpoint."""

    caplog.set_level(logging.INFO)

    # Build a Dynaconf Config rooted in a tmp settings.toml
    closed_port = _closed_port()
    settings = tmp_path / "settings.toml"
    settings.write_text(f"""
[default]
app_name = "resilience-test"
event_bus = "sessions"

[default.sessions_service]
base_url = "http://127.0.0.1:{closed_port}"
agent_id = "test-agent"
agent_type = "test"
capabilities = ["test"]
api_key = "test-key"
max_concurrent_jobs = 1
job_timeout_seconds = 5
sse_reconnect_delay_seconds = 60
sse_max_reconnect_attempts = 1
""")
    monkeypatch.setenv("SESSIONS_API_KEY", "test-key")
    monkeypatch.setenv("SESSION_KEY", "test-session-key")

    config = Config(settings_files=[str(settings)])

    app = AppBuilder(config).with_handler(_NullHandler).build()

    # TestClient triggers the lifespan startup → shutdown around the request.
    # If SessionsBus.on_startup blocked or raised, this would hang or fail.
    result: dict[str, object] = {"response": None, "error": None}

    def _run() -> None:
        try:
            with TestClient(app) as client:
                result["response"] = client.get("/")
        except Exception as exc:  # noqa: BLE001 - capture all to surface in main thread
            result["error"] = exc

    runner = threading.Thread(target=_run, daemon=True)
    runner.start()
    runner.join(timeout=_LIFESPAN_TIMEOUT_SECONDS)

    assert not runner.is_alive(), f"Startup blocked — lifespan did not complete within {_LIFESPAN_TIMEOUT_SECONDS}s"
    assert result["error"] is None, f"Unexpected error during lifespan: {result['error']!r}"
    response = result["response"]
    assert response is not None
    assert response.status_code == 200

    # Resilience claim is not just "TestClient survived" — it is "SessionsBus.on_startup
    # was invoked and acknowledged the unreachable backend without raising". Assert both
    # via the log channel so a future no-op on_startup cannot silently pass this test.
    assert any("SessionsBus connected" in rec.getMessage() for rec in caplog.records), (
        "SessionsBus.on_startup did not run — its 'connected' log line is missing. "
        "Test would pass trivially if on_startup were a no-op; that defeats the point."
    )
    assert any(
        "Lifecycle component SessionsBus startup completed" in rec.getMessage() for rec in caplog.records
    ), "AppBuilder lifespan never awaited SessionsBus.on_startup."
