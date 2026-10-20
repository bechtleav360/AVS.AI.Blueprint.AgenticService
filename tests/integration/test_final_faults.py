"""Faults no retry can fix, against a real broker (D23).

The broker answered, and its answer is final: a durable that filters another subject, a stream the
server refuses to create, a grant the account lacks. Each test lets the fault happen and observes
what an operator would -- the CRITICAL line, ``/health/live`` answering 503 with the agent and the
reason -- and that the client does not try again. The tenancy faults of a named connection are in
``test_named_connections.py``.

The agents are critical, as an unflagged agent is, so the framework also ends the process: it sends
SIGTERM to itself, and here the process is pytest, so that call is patched and asserted on.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from nats.aio.client import Client as NatsClient
from nats.js import api as js_api
from nats.js.client import JetStreamContext

from blueprint.agents.agent_group import AgentGroup
from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.clients.io.nats_client import JetStreamPermissionError, NATSClient
from blueprint.agents.component.component import Component
from blueprint.agents.config import Config
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent

from .conftest import base_settings
from .helpers import wait_until


def subscribing(topics: list[str]) -> type:
    """A handler that declares ``topics`` and runs nothing; the faults happen before any delivery."""

    class Subscribing(EventHandlerBase):
        async def on_startup(self) -> None:
            pass

        async def on_shutdown(self) -> None:
            pass

        def get_subscribed_topics(self) -> list[str]:
            return topics

        async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
            return True

        async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> None:
            return None

    return Subscribing


@asynccontextmanager
async def started(tmp_path: Path, settings: str, agents: dict[str, list[str]]) -> AsyncIterator[tuple[Any, dict[str, NATSClient]]]:
    """A running group of ``agents`` (name -> topics), without waiting for subscriptions: they never come."""
    (tmp_path / "settings.toml").write_text(settings, encoding="utf-8")
    config = Config(settings_files=["settings.toml"], root_path=str(tmp_path))
    group = AgentGroup("integration", {name: AppBuilder().with_handler(subscribing(topics)) for name, topics in agents.items()})
    try:
        app = group.assemble(config)
        async with app.router.lifespan_context(app):
            registry = Component.shared_registry
            assert registry is not None
            yield app, {name: registry.get_component(NATSClient, namespace=name) for name in agents}
    finally:
        Component.reset_shared_state()


async def liveness(app: Any) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://it") as http:
        return await http.get("/health/live")


def critical(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.levelno == logging.CRITICAL]


class TestADurableOfAnotherSubscription:
    """C1, S1 -- the durable the agent derives exists and filters another subject."""

    async def test_it_is_refused_once_and_takes_liveness_down(
        self,
        tmp_path: Path,
        nats_url: str,
        nats_connection: NatsClient,
        jetstream: JetStreamContext,
        jetstream_stream: str,
        subject_prefix: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        agent = f"orders_{subject_prefix}"
        topic = f"{subject_prefix}.orders.created"
        durable = f"{agent}-{topic.replace('.', '_')}-durable"
        await jetstream.add_consumer(
            jetstream_stream,
            config=js_api.ConsumerConfig(
                durable_name=durable, filter_subject=f"{subject_prefix}.other", ack_policy=js_api.AckPolicy.EXPLICIT
            ),
        )

        with patch("blueprint.agents.app_builder.signal.raise_signal") as raise_signal:
            async with started(tmp_path, base_settings(nats_url, jetstream_stream), {agent: [topic]}) as (app, _):
                await wait_until(lambda: raise_signal.called, timeout=15, description="the fatal handler to act")
                live = await liveness(app)
                refusals = sum("belongs to another subscription" in r.getMessage() for r in caplog.records)
                await asyncio.sleep(2.0)  # four retry delays (0.5 s): a retry would have shown by now
                assert sum("belongs to another subscription" in r.getMessage() for r in caplog.records) == refusals

        assert live.status_code == 503
        assert durable in live.json()["detail"]["agents"][agent]
        assert any(durable in message and "Not retried" in message for message in critical(caplog))
        info = await jetstream.consumer_info(jetstream_stream, durable)
        assert info.config.filter_subject == f"{subject_prefix}.other", "the other subscription's consumer is left as it was"


class TestAStreamTheServerRefuses:
    """The agent's stream would capture subjects another stream already captures."""

    async def test_it_is_refused_once_and_takes_liveness_down(
        self,
        tmp_path: Path,
        nats_url: str,
        jetstream: JetStreamContext,
        jetstream_stream: str,
        subject_prefix: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        agent = f"orders_{subject_prefix}"
        own_stream = f"{jetstream_stream}_OWN"
        settings = base_settings(nats_url, own_stream)
        with patch("blueprint.agents.app_builder.signal.raise_signal") as raise_signal:
            async with started(tmp_path, settings, {agent: [f"{subject_prefix}.orders.created"]}) as (app, _):
                await wait_until(lambda: raise_signal.called, timeout=15, description="the fatal handler to act")
                live = await liveness(app)

        assert live.status_code == 503
        reason = live.json()["detail"]["agents"][agent]
        assert own_stream in reason and "refused" in reason
        assert any("StreamConflictError" in message or f"stream '{own_stream}'" in message for message in critical(caplog))


class TestAGrantTheAccountLacks:
    """The agent's own connection may not make the JetStream requests consuming needs.

    Found by the health poll that connects every client before startup: the JetStream probe times
    out while the broker reports the refused grant. It used to read as a slow broker, the agent was
    paused as degraded and stayed so -- consuming nothing, retrying nothing, saying nothing.
    """

    async def test_it_fails_the_start(
        self, tmp_path: Path, accounts_url: str, subject_prefix: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        agent = f"orders_{subject_prefix}"
        # 'proc' may publish and subscribe nothing (nats-accounts.conf).
        settings = base_settings(accounts_url, f"IT_{subject_prefix.upper()}", 'nats_user = "proc"\nnats_password = "proc-test-only"\n')
        with pytest.raises(JetStreamPermissionError, match="refused this agent's connection a permission") as refused:
            async with started(tmp_path, settings, {agent: [f"{subject_prefix}.orders.created"]}):
                pass

        assert "$js.api" in str(refused.value).lower()
        assert "proc-test-only" not in str(refused.value)
        assert any("whatever 'critical_agents' says" in message for message in critical(caplog))
