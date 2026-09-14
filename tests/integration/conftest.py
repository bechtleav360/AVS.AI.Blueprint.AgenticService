"""Everything in this directory needs something running, and is marked so automatically.

The split used to be enforced three ways at once and agreed with itself in none of them (#80):
CI selected by *directory* (`tests/unit`), the `integration` marker was applied by *hand* to three
tests out of roughly sixty, and the rest of this directory was unmarked -- so `-m "not integration"`
deselected almost nothing, and `tests/integration/` was simultaneously red and invisible.

One rule now: **a test here requires an external service.** The marker is applied by location, so
the directory and the marker cannot drift apart and no contributor has to remember the decorator.
The other half of the rule is what this file cannot enforce and a review must -- a test that needs
nothing running does not belong here. Two that did were moved out rather than marked.

**A missing broker skips; it never fails.** An offline run of the whole suite has to stay green,
because `-m integration` is how you *ask* for the tests that need something running -- so the
absence of a server is not a result. The skip messages name the command that starts it, since the
reader of a skip is usually someone who did not know these needed anything.

The services:

    docker compose -f tests/integration/docker-compose.yml up -d
    pytest tests/ -m integration
"""

import asyncio
import os
import uuid
from urllib.parse import urlparse
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import nats
import pytest
from fastapi import FastAPI
from nats.aio.client import Client as NatsClient
from nats.js import JetStreamContext

from blueprint.agents.agent_group import AgentGroup
from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.clients.io.nats_client import NATSClient
from blueprint.agents.component.component import Component
from blueprint.agents.config import Config

from .helpers import wait_until

INTEGRATION_ROOT = Path(__file__).parent

NATS_URL = os.environ.get("BLUEPRINT_TEST_NATS_URL", "nats://127.0.0.1:4222")
"""Where the broker is.

Overridable, because a CI service container is not on localhost. The literal address rather than
``localhost`` is deliberate: ``localhost`` resolves to ``::1`` first here, and see
:func:`server_is_listening` for why that costs a minute per run when nothing is there.
"""

COMPOSE_HINT = "docker compose -f tests/integration/docker-compose.yml up -d"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test collected from this directory as ``integration``."""
    for item in items:
        if INTEGRATION_ROOT in Path(str(item.fspath)).parents:
            item.add_marker(pytest.mark.integration)


# ---------------------------------------------------------------------------
# The broker
# ---------------------------------------------------------------------------


def server_is_listening(url: str, timeout: float = 2.0) -> bool:
    """Is anything accepting TCP connections at ``url``? A plain socket, and a hard deadline.

    **Not** ``nats.connect``, which is the obvious way to write this and does not work offline.
    Two behaviours combine badly: an unreachable ``::1`` port on Windows silently drops the SYN
    rather than refusing it, so the attempt stalls for the whole ``connect_timeout``; and nats-py
    then retries the initial connect indefinitely -- ``max_reconnect_attempts`` governs
    *re*-connection, not the first one. An offline run of this directory therefore hung rather
    than skipping, which is the one thing these fixtures exist to prevent.

    A bare ``open_connection`` under ``wait_for`` has neither problem: no protocol handshake, no
    retry loop, and a deadline this function owns.
    """
    parsed = urlparse(url)
    host, port = parsed.hostname or "127.0.0.1", parsed.port or 4222

    async def probe() -> None:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
        await writer.wait_closed()

    try:
        asyncio.run(probe())
    except Exception:
        return False
    return True


@pytest.fixture(scope="session")
def nats_url() -> str:
    """The broker's URL, or skip the test because there is no broker.

    Probed once per session, and by socket rather than by client: a session-scoped fixture must
    not hold a connection either way, because pytest-asyncio gives each test its own event loop
    and a connection made on a loop that has since closed is unusable on the next.
    """
    if not server_is_listening(NATS_URL):
        pytest.skip(f"No NATS server at {NATS_URL}. Start one with: {COMPOSE_HINT}")
    return NATS_URL


@pytest.fixture
async def nats_connection(nats_url: str) -> AsyncIterator[NatsClient]:
    """A raw nats-py connection for the test to publish and assert with.

    Deliberately *not* the framework's client: a test that observes the broker through the same
    object it is testing can only confirm that object agrees with itself.
    """
    # allow_reconnect=False so that a broker disappearing mid-run fails the test that noticed
    # rather than parking it in nats-py's reconnect loop.
    connection = await nats.connect(nats_url, connect_timeout=2, allow_reconnect=False)
    try:
        yield connection
    finally:
        await connection.close()


@pytest.fixture
def subject_prefix() -> str:
    """A subject namespace unique to this test, so no two tests can see each other's messages.

    Every subject a test uses goes under here. Without it, a leftover durable from a previous
    run -- or a test running beside this one -- delivers into the assertion.
    """
    return f"it{uuid.uuid4().hex[:12]}"


@pytest.fixture
async def jetstream_stream(nats_connection: NatsClient, subject_prefix: str) -> AsyncIterator[str]:
    """Yield a stream name reserved for this test, and delete the stream afterwards.

    The stream is **not** created here. The framework creates its own (`_ensure_stream`), and a
    test of that behaviour has to watch it happen; a test that needs one up front creates it
    itself from this name. What the fixture guarantees is the teardown, which is the half that
    cannot be left to the test: deleting a stream deletes its consumers with it, and a durable
    that outlives its test carries a delivery count and a filter subject into the next one.
    """
    name = f"IT_{subject_prefix.upper()}"
    try:
        yield name
    finally:
        try:
            await nats_connection.jetstream().delete_stream(name)
        except Exception:
            # Never created, or already gone. Either is a legitimate end for a test that did
            # not get that far, and a teardown that raises would mask the real failure.
            pass


@pytest.fixture
async def jetstream(nats_connection: NatsClient, jetstream_stream: str, subject_prefix: str) -> JetStreamContext:
    """A JetStream context with this test's stream already created over its subject prefix."""
    js = nats_connection.jetstream()
    await js.add_stream(name=jetstream_stream, subjects=[f"{subject_prefix}.>"])
    return js


# ---------------------------------------------------------------------------
# An application built against the real broker
# ---------------------------------------------------------------------------


OUTBOUND_EVENT_TYPE = "order.validated"
"""The event type a test handler returns, mapped to ``<subject_prefix>.out`` by the config below."""


@pytest.fixture
def outbound_subject(subject_prefix: str) -> str:
    """Where a handler's ``HandlerResult`` is published, inside this test's own namespace."""
    return f"{subject_prefix}.out"


@pytest.fixture
def integration_config(
    tmp_path: Path,
    nats_url: str,
    jetstream_stream: str,
    subject_prefix: str,
    outbound_subject: str,
) -> Iterator[Config]:
    """A ``Config`` written to disk and loaded the way a deployed process loads one.

    Written as a file rather than mocked, because the keys under test -- ``nats_url``,
    ``nats_stream_name``, the consumer tuning -- are read through the same resolution a
    deployment uses, and a mock cannot be wrong about it in the way a settings file can.

    ``app_name`` has no whitespace on purpose: since P1 it is the root namespace's queue group,
    and ``validate_subject_segment`` rejects a space. That is not a fixture detail -- it is the
    defect `examples/webhook_relay` is sitting on.

    **``nats_queue_group`` is per test, and that is not cosmetic.** The dead-letter subject
    defaults to ``<queue group>.dead-letter`` and the client puts it into the stream it
    provisions, so with one shared queue group every test's stream claims
    ``blueprint-it.dead-letter`` -- and the second stream to be created is refused with
    *subjects overlap with an existing stream*. Found by leaving one stream behind and starting
    the next test.
    """
    settings = tmp_path / "settings.toml"
    settings.write_text(
        "[default]\n"
        'app_name = "blueprint-it"\n'
        'app_environment = "development"\n'
        "app_port = 8000\n"
        'model_provider = "openai"\n'
        'model_api_key = "not-a-real-key"\n'
        'event_bus = "nats"\n'
        f'nats_url = "{nats_url}"\n'
        f'nats_stream_name = "{jetstream_stream}"\n'
        f'nats_queue_group = "{subject_prefix}"\n'
        "nats_use_jetstream = true\n"
        # Well above any handler here, and short enough that a test asserting *no* redelivery can
        # afford to wait the whole window out. The framework default is 300.
        "nats_ack_wait = 2.0\n"
        "nats_max_deliver = 3\n"
        # The client retries the initial connect forever by default, which turns "the broker
        # refused this subscription" into a test that hangs instead of one that fails.
        "event_client_max_retries = 2\n"
        "event_client_retry_delay = 0.5\n\n"
        # Where a handler's HandlerResult goes. Without a mapping for the event type,
        # EventPublishingService logs "no topic mapping found" and publishes nothing at all.
        f'[default.event_publishing.topic_mapping."{OUTBOUND_EVENT_TYPE}"]\n'
        f'topic = "{outbound_subject}"\n',
        encoding="utf-8",
    )
    config = Config(settings_files=["settings.toml"], root_path=str(tmp_path))
    try:
        yield config
    finally:
        Component.reset_shared_state()


NatsAppFactory = Callable[..., Any]


@pytest.fixture
def nats_app(integration_config: Config) -> NatsAppFactory:
    """Return a context manager yielding a started, subscribed application on the real broker.

    Used as::

        async with nats_app(MyHandler) as (app, client):
            ...

    Two things it does that a test should not have to repeat:

    **The lifespan is entered directly**, not through ``TestClient``. Startup is where the client
    connects and subscribes; the test is already async, and ``TestClient`` would run that
    lifespan on a second event loop in a background thread.

    **It waits for the subscriptions.** ``NATSClient.subscribe()`` returns immediately and does
    the connecting in a background retry task, so the moment the lifespan returns, the agent is
    typically not yet on its topics. A test that published there would be asserting on a race:
    JetStream would hold the message and the test would usually pass, Core NATS would drop it
    and the test would usually fail, and neither outcome would be about the thing under test.

    At least one handler is required. With none, the agent neither consumes nor publishes, so
    ``build()`` deliberately gives it no transport client at all and there would be nothing to
    hand back.
    """

    @asynccontextmanager
    async def factory(*handlers: type, ready_timeout: float = 15.0) -> AsyncIterator[tuple[FastAPI, NATSClient]]:
        assert handlers, "nats_app needs at least one handler; without one the agent is given no transport client"

        builder = AppBuilder(integration_config)
        for handler in handlers:
            builder = builder.with_handler(handler)
        app = builder.build()

        try:
            async with app.router.lifespan_context(app):
                registry = Component.shared_registry
                assert registry is not None
                client: NATSClient = registry.get_component(NATSClient)

                await wait_until(
                    lambda: client.subscriptions_ready,
                    timeout=ready_timeout,
                    description=f"the NATS subscriptions of queue group '{client.queue_group}' to become ready",
                )
                yield app, client
        finally:
            # After the lifespan, never inside it. `Component.configure` refuses a second call and
            # the registry is process-global, so both have to go before a test can start a second
            # process -- but clearing them while shutdown is still running takes the components
            # out from under it, and a shutdown draining an in-flight handler then never returns.
            Component.reset_shared_state()

    return factory


@pytest.fixture
def agent_names(subject_prefix: str) -> tuple[str, str]:
    """Two agent names unique to this test.

    Unique because a namespaced client derives its queue group from the namespace, and the
    dead-letter subject from the queue group -- so two tests sharing an agent name would claim
    one dead-letter subject and their streams would overlap. The alphabet is ``[a-z][a-z0-9_]*``,
    which the ``it<hex>`` prefix already satisfies.
    """
    return f"orders_{subject_prefix}", f"billing_{subject_prefix}"


@pytest.fixture
def nats_group(integration_config: Config) -> NatsAppFactory:
    """Return a context manager yielding a *group* of agents started on the real broker.

    The single-agent ``nats_app`` cannot express what a group asserts. Each agent gets its own
    ``NATSClient``, its own queue group and its own durable, and the claim under test is that
    those stay separate while sharing one process, one connection pool and one stream.

    Used as::

        async with nats_group({"orders": OrdersHandler, "billing": BillingHandler}) as clients:
            ...

    and yields the clients by agent name, because every assertion here is about one agent's
    transport rather than about the application object they share.
    """

    @asynccontextmanager
    async def factory(agents: dict[str, type], *, ready_timeout: float = 20.0) -> AsyncIterator[dict[str, NATSClient]]:
        group = AgentGroup("integration", {name: AppBuilder().with_handler(handler) for name, handler in agents.items()})
        app = group.assemble(integration_config)

        try:
            async with app.router.lifespan_context(app):
                registry = Component.shared_registry
                assert registry is not None
                clients = {name: registry.get_component(NATSClient, namespace=name) for name in agents}

                for name, client in clients.items():
                    await wait_until(
                        lambda client=client: client.subscriptions_ready,  # type: ignore[misc]
                        timeout=ready_timeout,
                        description=f"agent '{name}' to subscribe",
                    )
                yield clients
        finally:
            # After the lifespan, for the reason given on `nats_app`.
            Component.reset_shared_state()

    return factory
