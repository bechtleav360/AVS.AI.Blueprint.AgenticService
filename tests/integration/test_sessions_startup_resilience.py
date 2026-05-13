"""Integration test: AppBuilder.build() with event_bus='sessions' yields a
FastAPI app whose lifespan completes even when the sessions service URL is
unreachable. Standard REST endpoints (the framework root API) must respond.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.component.component import Component
from blueprint.agents.config import Config
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent


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


def test_app_starts_when_sessions_service_unreachable(tmp_path, monkeypatch):
    """With sessions URL pointed at a closed port, build() returns and
    TestClient can hit the root endpoint."""

    # Build a Dynaconf Config rooted in a tmp settings.toml
    settings = tmp_path / "settings.toml"
    settings.write_text(
        """
[default]
app_name = "resilience-test"
event_bus = "sessions"

[default.sessions_service]
base_url = "http://127.0.0.1:1"
agent_id = "test-agent"
agent_type = "test"
capabilities = ["test"]
api_key = "test-key"
max_concurrent_jobs = 1
job_timeout_seconds = 5
sse_reconnect_delay_seconds = 60
sse_max_reconnect_attempts = 1
"""
    )
    monkeypatch.setenv("SESSIONS_API_KEY", "test-key")
    monkeypatch.setenv("SESSION_KEY", "test-session-key")

    config = Config(settings_files=[str(settings)])

    app = (
        AppBuilder(config)
        .with_handler(_NullHandler)
        .build()
    )

    # TestClient triggers the lifespan startup → shutdown around the request.
    # If SessionsBus.on_startup blocked or raised, this would hang or fail.
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
