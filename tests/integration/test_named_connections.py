"""Named connections against a broker with one account per tenant (nats-accounts in docker-compose.yml).

What a tenant deployment depends on, observed rather than asserted on the client's own state:

- the framework binds to consumers the operator made, sends no JetStream API request, and its
  process connection subscribes nothing -- so the restricted accounts report no permission violation;
- a run sees one tenant only: its connection, the source's run scope and the event's tenant agree;
- a delivery the source rejects never runs and is termed;
- a subject the source does not claim fails startup unless the hybrid mode is asked for;
- connections added, changed and removed at runtime lose and duplicate nothing;
- a tenant connection that cannot log in moves readiness as ``nats_connections_readiness`` says,
  and never pauses the agent: its other connection keeps delivering.
"""

import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
import nats
import pytest

from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent

from .connection_source import SCOPE, SOURCES, binding_for, stream_for, subject_prefix_for
from .helpers import poll_until, wait_until

ADMINS = {"A": ("admin-a", "admin-a-test-only"), "B": ("admin-b", "admin-b-test-only")}


def recording_handler(topics: list[str], runs: list[dict[str, Any]]) -> type:
    class Recording(EventHandlerBase):
        async def on_startup(self) -> None:
            pass

        async def on_shutdown(self) -> None:
            pass

        def get_subscribed_topics(self) -> list[str]:
            return topics

        async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
            return True

        async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> None:
            runs.append(
                {
                    "id": event.id,
                    "connection": context.get("nats_connection"),
                    "scope": SCOPE.get(),
                    "tenant": (event.model_extra or {}).get("tenantid"),
                    "subject": context.get("nats_subject"),
                }
            )
            return None

    return Recording


Operator = Callable[[list[str], dict[str, list[str]]], Awaitable[None]]


@pytest.fixture
async def operator(accounts_url: str, subject_prefix: str) -> AsyncIterator[Operator]:
    """Provision what the deployment owns: a stream per tenant and the agents' consumers. Removed after the test."""
    made: set[str] = set()

    async def provision(tenants: list[str], agents: dict[str, list[str]]) -> None:
        for tenant in tenants:
            user, password = ADMINS[tenant]
            admin = await nats.connect(accounts_url, user=user, password=password)
            jsm = admin.jsm()
            stream = stream_for(subject_prefix, tenant)
            if tenant not in made:
                await jsm.add_stream(name=stream, subjects=[f"{subject_prefix_for(subject_prefix, tenant)}>"])
                made.add(tenant)
            for agent, subjects in agents.items():
                await jsm.add_consumer(stream, config=binding_for(subject_prefix, agent, tuple(subjects), tenant).consumer_config())
            await admin.close()

    yield provision

    for tenant in made:
        user, password = ADMINS[tenant]
        admin = await nats.connect(accounts_url, user=user, password=password)
        try:
            await admin.jsm().delete_stream(stream_for(subject_prefix, tenant))
        finally:
            await admin.close()


async def publish(accounts_url: str, prefix: str, tenant: str, subject: str, *, claimed_tenant: str | None = None) -> str:
    user, password = ADMINS[tenant]
    admin = await nats.connect(accounts_url, user=user, password=password)
    event_id = str(uuid.uuid4())
    body = {"specversion": "1.0", "id": event_id, "type": subject, "source": "integration-test", "tenantid": claimed_tenant or tenant}
    await admin.jetstream().publish(f"{subject_prefix_for(prefix, tenant)}{subject}", json.dumps(body).encode())
    await admin.close()
    return event_id


async def consumer_info(accounts_url: str, prefix: str, tenant: str, agent: str) -> Any:
    user, password = ADMINS[tenant]
    admin = await nats.connect(accounts_url, user=user, password=password)
    try:
        return await admin.jsm().consumer_info(stream_for(prefix, tenant), f"d-{agent}")
    finally:
        await admin.close()


def settings(
    accounts_url: str, prefix: str, tenants: list[str], extra: str = "", *, user: str = "proc", password: str = "proc-test-only"
) -> str:
    return (
        "[default]\n"
        'app_name = "blueprint-it"\n'
        'app_environment = "development"\n'
        "app_port = 8000\n"
        'model_provider = "openai"\n'
        'event_bus = "nats"\n'
        f'nats_url = "{accounts_url}"\n'
        f'nats_user = "{user}"\n'
        f'nats_password = "{password}"\n'
        "event_client_max_retries = 2\n"
        "event_client_retry_delay = 0.5\n"
        'nats_connection_source = "tests.integration.connection_source:create_source"\n'
        f'test_source_url = "{accounts_url}"\n'
        f'test_source_prefix = "{prefix}"\n'
        f"test_source_tenants = {json.dumps(tenants)}\n" + extra
    )


def permission_violations(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Permission violations the broker reported to any connection of the process, as logged."""
    found = []
    for record in caplog.records:
        text = record.getMessage() + (str(record.exc_info[1]) if record.exc_info and record.exc_info[1] else "")
        if "ermission" in text:
            found.append(text[:200])
    return found


class TestTenantsAreKeptApart:
    async def test_each_run_sees_one_tenant_on_consumers_the_operator_made(
        self, settings_group: Any, operator: Operator, accounts_url: str, subject_prefix: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING)
        risk, both = f"risk_{subject_prefix}", f"both_{subject_prefix}"
        agents_subjects = {risk: ["risk.>"], both: ["risk.>", "issue.>"]}
        await operator(["A", "B"], agents_subjects)
        before = (await consumer_info(accounts_url, subject_prefix, "A", both)).config.as_dict()
        runs: list[dict[str, Any]] = []
        agents = {name: recording_handler(subjects, runs) for name, subjects in agents_subjects.items()}

        async with settings_group(
            settings(accounts_url, subject_prefix, ["A", "B"], "nats_max_concurrent_runs = 2\n"), agents, named=2
        ) as clients:
            assert all(list(client._topic_callbacks) == [] for client in clients.values()), "nothing on the process connection"
            for tenant in ("A", "B"):
                for _ in range(3):
                    await publish(accounts_url, subject_prefix, tenant, "risk.created")
                for _ in range(2):
                    await publish(accounts_url, subject_prefix, tenant, "issue.created")
            await wait_until(lambda: len(runs) == 16, timeout=15, description="16 runs (risk agent 6, both agent 10)")

            async def settled() -> bool:
                infos = [await consumer_info(accounts_url, subject_prefix, t, a) for t in ("A", "B") for a in agents_subjects]
                return all(info.num_ack_pending == 0 and info.num_redelivered == 0 for info in infos)

            await poll_until(settled, timeout=10, description="every delivery acked, none redelivered")

        assert [run for run in runs if not run["connection"] == run["scope"] == run["tenant"]] == []
        assert {run["subject"] for run in runs} == {"risk.created", "issue.created"}, "the handler sees the subject without the prefix"
        after = (await consumer_info(accounts_url, subject_prefix, "A", both)).config.as_dict()
        assert after == before, "the operator's consumer is bound, never rewritten"
        assert permission_violations(caplog) == []

    async def test_a_delivery_the_source_rejects_never_runs_and_is_termed(
        self, settings_group: Any, operator: Operator, accounts_url: str, subject_prefix: str
    ) -> None:
        agent = f"risk_{subject_prefix}"
        await operator(["A"], {agent: ["risk.>"]})
        runs: list[dict[str, Any]] = []
        async with settings_group(settings(accounts_url, subject_prefix, ["A"]), {agent: recording_handler(["risk.>"], runs)}, named=1):
            await publish(accounts_url, subject_prefix, "A", "risk.created", claimed_tenant="B")
            good = await publish(accounts_url, subject_prefix, "A", "risk.created")
            await wait_until(lambda: [run["id"] for run in runs] == [good], timeout=10, description="only the matching event to run")

            async def termed() -> bool:
                info = await consumer_info(accounts_url, subject_prefix, "A", agent)
                return info.delivered.stream_seq == 2 and info.num_ack_pending == 0 and info.num_redelivered == 0

            await poll_until(termed, timeout=10, description="the rejected delivery to be settled for good")


class TestClaims:
    async def test_an_unclaimed_subject_fails_startup(
        self, settings_group: Any, operator: Operator, accounts_url: str, subject_prefix: str
    ) -> None:
        agent = f"risk_{subject_prefix}"
        await operator(["A"], {agent: ["risk.>"]})
        extra = 'test_source_unclaimed = ["hybrid.tick"]\n'
        with pytest.raises(Exception, match="does not claim"):
            async with settings_group(
                settings(accounts_url, subject_prefix, ["A"], extra), {agent: recording_handler(["risk.>", "hybrid.tick"], [])}
            ):
                pass

    async def test_the_hybrid_mode_serves_it_on_the_process_connection_when_asked_for(
        self, settings_group: Any, operator: Operator, accounts_url: str, subject_prefix: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING)
        agent, tick = f"risk_{subject_prefix}", f"hybrid.{subject_prefix}.tick"
        await operator(["A"], {agent: ["risk.>"]})
        extra = f'test_source_unclaimed = ["{tick}"]\nnats_unclaimed_subjects = "default_connection"\n'
        runs: list[dict[str, Any]] = []
        handler = recording_handler(["risk.>", tick], runs)
        config = settings(accounts_url, subject_prefix, ["A"], extra, user="proc-hybrid", password="proc-hybrid-test-only")
        async with settings_group(config, {agent: handler}, named=1) as clients:
            assert list(clients[agent]._topic_callbacks) == [tick]
            publisher = await nats.connect(accounts_url, user="proc-hybrid", password="proc-hybrid-test-only")
            event = {"specversion": "1.0", "id": str(uuid.uuid4()), "type": "tick", "source": "integration-test"}
            await publisher.publish(tick, json.dumps(event).encode())
            await publisher.close()
            await publish(accounts_url, subject_prefix, "A", "risk.created")
            await wait_until(lambda: len(runs) == 2, timeout=10, description="the tick (process connection) and the tenant event")
        assert sorted(str(run["connection"]) for run in runs) == ["A", "None"]
        assert permission_violations(caplog) == []


class TestConnectionsChangeAtRuntime:
    async def test_added_changed_and_removed_without_loss_or_duplicate(
        self, settings_group: Any, operator: Operator, accounts_url: str, subject_prefix: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING)
        agent = f"risk_{subject_prefix}"
        await operator(["A", "B"], {agent: ["risk.>"]})
        runs: list[dict[str, Any]] = []
        async with settings_group(
            settings(accounts_url, subject_prefix, ["A"]), {agent: recording_handler(["risk.>"], runs)}, named=1
        ) as clients:
            client, source = clients[agent], SOURCES[-1]

            source.set_users({"A": "agent-a", "B": "agent-b"})  # added
            await wait_until(
                lambda: client.named_connections == ("A", "B") and all(b.subscriptions_ready for b in client._named),
                timeout=10,
                description="B to be bound",
            )
            on_b = await publish(accounts_url, subject_prefix, "B", "risk.created")
            await wait_until(lambda: on_b in [run["id"] for run in runs], timeout=10, description="B's event to run")

            sent = [await publish(accounts_url, subject_prefix, "A", "risk.created") for _ in range(5)]
            source.set_users({"A": "agent-a2", "B": "agent-b"})  # changed: the same account, rotated user
            sent += [await publish(accounts_url, subject_prefix, "A", "risk.created") for _ in range(10)]
            await wait_until(
                lambda: all(event_id in [run["id"] for run in runs] for event_id in sent),
                timeout=15,
                description="every event on A across the change",
            )
            await wait_until(
                lambda: len([b for b in client._named if b.link.name == "A"]) == 1,
                timeout=10,
                description="the old link of A to be retired",
            )
            handled = [run["id"] for run in runs if run["connection"] == "A"]
            assert sorted(handled) == sorted(sent), "nothing lost, nothing twice"

            source.set_users({"A": "agent-a2"})  # removed
            await wait_until(lambda: client.named_connections == ("A",), timeout=10, description="B to be removed")
        info = await consumer_info(accounts_url, subject_prefix, "A", agent)
        assert info.num_ack_pending == 0 and info.num_redelivered == 0
        assert permission_violations(caplog) == []


class TestADeadConnectionCountsForReadinessOnly:
    """Step 5 / D5: a tenant whose connection cannot log in never pauses the agent on its other tenants."""

    @pytest.mark.parametrize("mode, ready", [("never", True), ("any", True), ("all", False)])
    async def test_readiness_follows_the_mode_and_nothing_is_paused(
        self, settings_group: Any, operator: Operator, accounts_url: str, subject_prefix: str, mode: str, ready: bool
    ) -> None:
        agent = f"risk_{subject_prefix}"
        await operator(["A", "B"], {agent: ["risk.>"]})
        runs: list[dict[str, Any]] = []
        extra = f'test_source_wrong_password = ["B"]\nnats_connections_readiness = "{mode}"\nhealth_check_interval_seconds = 1\n'
        apps: list[Any] = []
        async with settings_group(
            settings(accounts_url, subject_prefix, ["A", "B"], extra), {agent: recording_handler(["risk.>"], runs)}, named=1, apps=apps
        ) as clients:
            client = clients[agent]
            await wait_until(
                lambda: {s.name: s.state for s in client.named_connection_states()} == {"A": "bound", "B": "retrying"},
                timeout=15,
                description="A bound, B retrying",
            )
            (b,) = [s for s in client.named_connection_states() if s.name == "B"]
            assert "wrong-test-only" not in b.describe()

            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=apps[0]), base_url="http://it") as http:

                async def probe_settled() -> bool:
                    response = await http.get("/health/ready")
                    # The payload of a poll after both connections were tried, not the startup one.
                    return (response.status_code == 200) is ready and "B=retrying" in response.text

                await poll_until(probe_settled, timeout=10, description=f"readiness {'UP' if ready else 'DOWN'} under '{mode}'")
                body = (await http.get("/health/ready")).json()
            payload = body if ready else body["detail"]
            entry = payload["components"][f"{agent}.nats_client:connections"]
            assert "B=retrying" in entry["message"] and "wrong-test-only" not in json.dumps(payload)

            assert not client.consumption_paused, "a dead named connection never pauses the agent"
            sent = await publish(accounts_url, subject_prefix, "A", "risk.created")
            await wait_until(lambda: sent in [run["id"] for run in runs], timeout=10, description="A to keep delivering")
