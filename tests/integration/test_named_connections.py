"""Named connections against a broker with one account per tenant (nats-accounts in docker-compose.yml).

What a tenant deployment depends on, observed rather than asserted on the client's own state:

- the framework binds to consumers the operator made, sends no JetStream API request, and its
  process connection subscribes nothing -- so the restricted accounts report no permission violation;
- a run sees one tenant only: its connection, the source's run scope and the event's tenant agree;
- a delivery the source rejects never runs and is termed;
- a subject the source does not claim fails startup unless the hybrid mode is asked for;
- connections added, changed and removed at runtime lose and duplicate nothing;
- a tenant connection that cannot reach its broker moves readiness as ``nats_connections_readiness``
  says, and never pauses the agent: its other connection keeps delivering;
- a tenancy fault -- a refused login, a refused deliver subject -- is not retried: the connection
  reads ``failed``, the fault is logged CRITICAL, liveness answers 503, and a critical agent ends the
  process (D23).
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from unittest.mock import patch

import httpx
import nats
import pytest

from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.errors import RetryableHandlerError
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


async def publish(
    accounts_url: str, prefix: str, tenant: str, subject: str, *, claimed_tenant: str | None = None, event_id: str | None = None
) -> str:
    user, password = ADMINS[tenant]
    admin = await nats.connect(accounts_url, user=user, password=password)
    event_id = event_id or str(uuid.uuid4())
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

    async def test_dedup_keeps_the_connections_apart(
        self, settings_group: Any, operator: Operator, accounts_url: str, subject_prefix: str, tmp_path: Any
    ) -> None:
        """T1 -- the same producer's (source, id) on two connections is two events; a repeat on one is a duplicate."""
        agent = f"risk_{subject_prefix}"
        await operator(["A", "B"], {agent: ["risk.>"]})
        runs: list[dict[str, Any]] = []
        # The agent's own section: the group's root has no cache to claim in.
        extra = (
            f"[default.{agent}]\n"
            "idempotency_enabled = true\n"
            "idempotency_ttl = 600\n"
            f"[default.{agent}.cache]\n"
            f'cache_dir = "{(tmp_path / "cache").as_posix()}"\n'
        )
        async with settings_group(
            settings(accounts_url, subject_prefix, ["A", "B"], extra), {agent: recording_handler(["risk.>"], runs)}, named=2, cache=True
        ):
            shared_id = str(uuid.uuid4())
            for tenant in ("A", "B", "A"):
                await publish(accounts_url, subject_prefix, tenant, "risk.created", event_id=shared_id)
            await wait_until(lambda: len(runs) == 2, timeout=10, description="one run per connection")

            async def settled() -> bool:
                infos = [await consumer_info(accounts_url, subject_prefix, tenant, agent) for tenant in ("A", "B")]
                return [info.delivered.stream_seq for info in infos] == [2, 1] and all(info.num_ack_pending == 0 for info in infos)

            await poll_until(settled, timeout=10, description="every delivery acked, the repeat on A included")

        assert sorted(run["connection"] for run in runs) == ["A", "B"]


class TestTheAttemptOnANamedConnection:
    async def test_a_redelivery_shows_attempt_2_and_the_bindings_limit(
        self, settings_group: Any, operator: Operator, accounts_url: str, subject_prefix: str
    ) -> None:
        """The binding's max_deliver (3 in connection_source.binding_for), not the agent's own key."""
        agent = f"risk_{subject_prefix}"
        await operator(["A"], {agent: ["risk.>"]})
        seen: list[tuple[Any, Any]] = []

        class FailsOnce(EventHandlerBase):
            async def on_startup(self) -> None:
                pass

            async def on_shutdown(self) -> None:
                pass

            def get_subscribed_topics(self) -> list[str]:
                return ["risk.>"]

            async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
                return True

            async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> None:
                seen.append((context.get("nats_delivery_attempt"), context.get("nats_max_deliver")))
                if len(seen) == 1:
                    raise RetryableHandlerError(status="retry", reason="first attempt fails on purpose")

        async with settings_group(settings(accounts_url, subject_prefix, ["A"]), {agent: FailsOnce}, named=1):
            await publish(accounts_url, subject_prefix, "A", "risk.created")
            await wait_until(lambda: len(seen) >= 2, timeout=15, description="the redelivery after the nak")
        assert seen == [(1, 3), (2, 3)]


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


class TestAChangeThatHasNotBoundYet:
    """M3 -- a binding superseded before it bound must not strand the one still delivering."""

    async def test_a_second_change_retires_the_link_that_was_still_delivering(
        self, settings_group: Any, operator: Operator, accounts_url: str, subject_prefix: str
    ) -> None:
        agent = f"risk_{subject_prefix}"
        await operator(["A"], {agent: ["risk.>"]})
        runs: list[dict[str, Any]] = []
        async with settings_group(
            settings(accounts_url, subject_prefix, ["A"]), {agent: recording_handler(["risk.>"], runs)}, named=1
        ) as clients:
            client, source = clients[agent], SOURCES[-1]
            first = client._named[0].link.nats_client

            source.set_users({"A": "agent-a2"}, unreachable={"A"})  # changed, and it cannot connect (yet)
            await wait_until(lambda: len(client._named) == 2, timeout=10, description="the changed binding to be added")
            assert not first.is_closed, "the old link serves while the new one cannot bind"

            source.set_users({"A": "agent-a2"}, unreachable=set())  # changed again, now it can
            await wait_until(lambda: first.is_closed, timeout=15, description="the first link to be retired")
            await wait_until(
                lambda: len(client._named) == 1 and client._named[0].subscriptions_ready, timeout=10, description="one bound binding"
            )
            sent = [await publish(accounts_url, subject_prefix, "A", "risk.created") for _ in range(5)]
            await wait_until(lambda: all(e in [run["id"] for run in runs] for e in sent), timeout=10, description="5 events")

        assert sorted(run["id"] for run in runs) == sorted(sent), "each once"

    async def test_removing_it_retires_the_link_that_was_still_delivering(
        self, settings_group: Any, operator: Operator, accounts_url: str, subject_prefix: str
    ) -> None:
        agent = f"risk_{subject_prefix}"
        await operator(["A"], {agent: ["risk.>"]})
        async with settings_group(
            settings(accounts_url, subject_prefix, ["A"]), {agent: recording_handler(["risk.>"], [])}, named=1
        ) as clients:
            client, source = clients[agent], SOURCES[-1]
            first = client._named[0].link.nats_client
            source.set_users({"A": "agent-a2"}, unreachable={"A"})
            await wait_until(lambda: len(client._named) == 2, timeout=10, description="the changed binding to be added")

            source.set_users({})
            await wait_until(lambda: client._named == [], timeout=15, description="both bindings to be retired")
            assert first.is_closed


class TestARefusedSubscriptionIsNotBound:
    """M4 -- the broker refuses a subscription through error_cb only; subscribe() returned and it read as bound.

    D23 -- and the refusal is a tenancy fault: final, not retried.
    """

    async def test_it_reads_failed_with_a_permission_violation(
        self, settings_group: Any, operator: Operator, accounts_url: str, subject_prefix: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        agent = f"risk_{subject_prefix}"
        await operator(["A"], {agent: ["risk.>"]})
        extra = 'test_source_foreign_deliver = ["A"]\n'
        with patch("blueprint.agents.app_builder.signal.raise_signal") as raise_signal:
            async with settings_group(
                settings(accounts_url, subject_prefix, ["A"], extra), {agent: recording_handler(["risk.>"], [])}, named=0
            ) as clients:
                client = clients[agent]
                await wait_until(lambda: client._named[0].failed, timeout=10, description="the binding to fail")
                state = client._state_of(client._named[0])
                assert (state.state, state.permission_denied) == ("failed", True)
                assert client._named[0].subscriptions_ready is False
                attempts = sum("refused the subscription to deliver subject" in r.getMessage() for r in caplog.records)
                await asyncio.sleep(2.0)  # longer than event_client_retry_delay: a retry would have shown by now
                assert sum("refused the subscription to deliver subject" in r.getMessage() for r in caplog.records) == attempts
        assert raise_signal.called, "a critical agent ends the process"
        assert any(r.levelno == logging.CRITICAL and "deliver subject" in r.getMessage() for r in caplog.records)


class TestARefusedLoginIsATenancyFault:
    """D23 -- the credentials the source hands over are wrong for the tenant's broker: CRITICAL, liveness DOWN."""

    async def test_it_reads_failed_and_liveness_answers_503(
        self, settings_group: Any, operator: Operator, accounts_url: str, subject_prefix: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        agent = f"risk_{subject_prefix}"
        await operator(["A", "B"], {agent: ["risk.>"]})
        runs: list[dict[str, Any]] = []
        apps: list[Any] = []
        extra = 'test_source_wrong_password = ["B"]\n'
        with patch("blueprint.agents.app_builder.signal.raise_signal") as raise_signal:
            async with settings_group(
                settings(accounts_url, subject_prefix, ["A", "B"], extra), {agent: recording_handler(["risk.>"], runs)}, named=1, apps=apps
            ) as clients:
                client = clients[agent]
                await wait_until(
                    lambda: {s.name: s.state for s in client.named_connection_states()} == {"A": "bound", "B": "failed"},
                    timeout=15,
                    description="A bound, B failed",
                )
                (b,) = [s for s in client.named_connection_states() if s.name == "B"]
                assert "refused the login" in b.last_error and "wrong-test-only" not in b.describe()
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=apps[0]), base_url="http://it") as http:
                    live = await http.get("/health/live")
                assert live.status_code == 503
                assert "refused the login" in live.json()["detail"]["agents"][agent]
                assert "wrong-test-only" not in live.text
        assert raise_signal.called, "a critical agent ends the process"
        critical = [r.getMessage() for r in caplog.records if r.levelno == logging.CRITICAL]
        assert any("named connection 'B'" in message and "refused the login" in message for message in critical)
        assert all("wrong-test-only" not in message for message in critical)


class TestStatusMessagesOfAnOperatorsConsumer:
    """S2 -- binding mode subscribes plainly, so the consumer's heartbeats and flow control reach the handler."""

    async def test_heartbeats_and_flow_control_never_reach_a_handler(
        self, settings_group: Any, operator: Operator, accounts_url: str, subject_prefix: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING)
        agent = f"risk_{subject_prefix}"
        await operator(["A"], {})
        user, password = ADMINS["A"]
        admin = await nats.connect(accounts_url, user=user, password=password)
        config = binding_for(subject_prefix, agent, ("risk.>",), "A").consumer_config()
        config.idle_heartbeat = 0.5
        config.flow_control = True
        await admin.jsm().add_consumer(stream_for(subject_prefix, "A"), config=config)
        await admin.close()
        runs: list[dict[str, Any]] = []
        async with settings_group(settings(accounts_url, subject_prefix, ["A"]), {agent: recording_handler(["risk.>"], runs)}, named=1):
            sent = [await publish(accounts_url, subject_prefix, "A", "risk.created") for _ in range(20)]
            await wait_until(lambda: len(runs) == 20, timeout=15, description="20 runs")
            await asyncio.sleep(2.0)  # several idle heartbeats

            async def settled() -> bool:
                info = await consumer_info(accounts_url, subject_prefix, "A", agent)
                return info.num_ack_pending == 0 and info.num_redelivered == 0

            await poll_until(settled, timeout=10, description="every delivery acked once")

        assert sorted(run["id"] for run in runs) == sorted(sent)
        assert [r.getMessage() for r in caplog.records if "unparseable" in r.getMessage() or "matches none" in r.getMessage()] == []


class TestADeadConnectionCountsForReadinessOnly:
    """Step 5 / D5: a tenant whose connection cannot reach its broker never pauses the agent on its other tenants.

    A fault that may heal; a refused login is a tenancy fault and is not retried (D23, above).
    """

    @pytest.mark.parametrize("mode, ready", [("never", True), ("any", True), ("all", False)])
    async def test_readiness_follows_the_mode_and_nothing_is_paused(
        self, settings_group: Any, operator: Operator, accounts_url: str, subject_prefix: str, mode: str, ready: bool
    ) -> None:
        agent = f"risk_{subject_prefix}"
        await operator(["A", "B"], {agent: ["risk.>"]})
        runs: list[dict[str, Any]] = []
        extra = f'test_source_unreachable = ["B"]\nnats_connections_readiness = "{mode}"\nhealth_check_interval_seconds = 1\n'
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


class TestThePublishRouteRefusesATenantSubject:
    """B1 -- an anonymous POST put an event into a tenant's stream, to run under the tenant's identity."""

    async def test_403_for_a_tenant_subject_and_nothing_runs(
        self, settings_group: Any, operator: Operator, accounts_url: str, subject_prefix: str
    ) -> None:
        agent = f"risk_{subject_prefix}"
        await operator(["A"], {agent: ["risk.>"]})
        runs: list[dict[str, Any]] = []
        apps: list[Any] = []
        tenant_subject = f"{subject_prefix_for(subject_prefix, 'A')}risk.created"
        event = {"specversion": "1.0", "id": str(uuid.uuid4()), "source": "/x", "type": "risk.created", "data": {}}
        async with settings_group(
            settings(accounts_url, subject_prefix, ["A"]), {agent: recording_handler(["risk.>"], runs)}, named=1, apps=apps
        ):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=apps[0]), base_url="http://it") as http:
                refused = await http.post(f"/api/{agent}/nats/events/{tenant_subject}", json=event)
                other = await http.post(f"/api/{agent}/nats/events/{subject_prefix}.elsewhere", json=event)
            await asyncio.sleep(1.0)

        assert refused.status_code == 403, refused.text
        assert "tenant subject" in refused.json()["detail"]
        assert other.status_code == 200, other.text
        assert runs == [], "nothing reached the tenant's stream"
