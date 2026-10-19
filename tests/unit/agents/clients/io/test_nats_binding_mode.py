"""Binding mode: an agent consumes through a consumer the deployment defines (named-connections plan, step 2)."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from nats.js import api as js_api
from nats.js.errors import APIError, NotFoundError

from blueprint.agents.clients.io.nats_client import JetStreamBindingError, NATSClient, _Binding
from blueprint.agents.clients.io.nats_connections import JetStreamBinding
from blueprint.agents.models.errors import RetryableHandlerError
from blueprint.agents.models.events import CloudEvent

PREFIX = "t.01900000-0000-7000-8000-0000000000a1."


def _spec(**overrides: object) -> JetStreamBinding:
    values: dict = {
        "subjects": ("risk.>",),
        "stream": "NOTIFICATIONS_A",
        "durable": "acme-agent-risk",
        "deliver_subject": "acme.agent.A.risk",
        "deliver_group": "risk",
        "ack_wait": 600.0,
        "subject_prefix": PREFIX,
        "max_deliver": 5,
        "deliver_policy": js_api.DeliverPolicy.NEW,
    }
    values.update(overrides)
    return JetStreamBinding(**values)


def _delivery(cloud_event: CloudEvent, subject: str = f"{PREFIX}risk.created", delivered: int = 1) -> MagicMock:
    msg = MagicMock(data=json.dumps(dict(cloud_event)).encode(), reply="$JS.ACK.x", subject=subject)
    for name in ("ack", "nak", "term", "in_progress"):
        setattr(msg, name, AsyncMock())
    msg.metadata.num_delivered = delivered
    return msg


@pytest.fixture
def jsm() -> MagicMock:
    manager = MagicMock()
    manager.stream_info = AsyncMock()
    manager.add_consumer = AsyncMock()
    manager.delete_consumer = AsyncMock()
    return manager


async def _bound(
    nats_client: NATSClient, mock_nats_core: MagicMock, jsm: MagicMock, callback, **overrides: object
) -> tuple[_Binding, object]:
    """Bind a binding-mode binding on the client's link and return it with its broker callback."""
    mock_nats_core.jsm = MagicMock(return_value=jsm)
    nats_client._link.nats_client = mock_nats_core
    spec = _spec(**overrides)
    binding = _Binding(link=nats_client._link, jetstream=spec, topic_callbacks=dict.fromkeys(spec.subjects, callback))
    await nats_client._subscribe_all(binding)
    return binding, mock_nats_core.subscribe.await_args.kwargs["cb"]


async def _settled(binding: _Binding, handler, msg: MagicMock) -> None:
    await handler(msg)
    await asyncio.gather(*list(binding.runs), return_exceptions=True)


class TestTheBindingItself:
    def test_filter_subjects_are_prefix_plus_declared(self) -> None:
        assert _spec(subjects=("risk.>", "issue.created")).filter_subjects == (f"{PREFIX}risk.>", f"{PREFIX}issue.created")

    def test_the_consumer_carries_the_wire_values_verbatim(self) -> None:
        """What the first consumer's own connection pool creates for the same input."""
        assert _spec().consumer_config() == js_api.ConsumerConfig(
            name="acme-agent-risk",
            durable_name="acme-agent-risk",
            deliver_subject="acme.agent.A.risk",
            deliver_group="risk",
            filter_subjects=[f"{PREFIX}risk.>"],
            ack_policy=js_api.AckPolicy.EXPLICIT,
            ack_wait=600.0,
            max_deliver=5,
            deliver_policy=js_api.DeliverPolicy.NEW,
        )

    def test_the_agent_sees_its_own_subject(self) -> None:
        spec = _spec()
        assert spec.local_subject(f"{PREFIX}risk.created") == "risk.created"
        assert spec.topic_for("risk.created") == "risk.>"
        assert spec.topic_for("issue.created") is None

    @pytest.mark.parametrize("overrides", [{"subjects": ()}, {"ack_wait": 0}], ids=["no-subject", "no-ack-wait"])
    def test_an_unusable_binding_is_refused(self, overrides: dict) -> None:
        with pytest.raises(ValueError):
            _spec(**overrides)


class TestBinding:
    async def test_an_unmanaged_binding_sends_no_jetstream_request(
        self, nats_client: NATSClient, mock_nats_core: MagicMock, jsm: MagicMock
    ) -> None:
        """The account may only be allowed to receive and acknowledge."""
        await _bound(nats_client, mock_nats_core, jsm, AsyncMock())
        mock_nats_core.jsm.assert_not_called()
        mock_nats_core.subscribe.assert_awaited_once()
        assert mock_nats_core.subscribe.await_args.args == ("acme.agent.A.risk",)
        assert mock_nats_core.subscribe.await_args.kwargs["queue"] == "risk"

    async def test_a_managed_binding_creates_its_consumer(self, nats_client: NATSClient, mock_nats_core: MagicMock, jsm: MagicMock) -> None:
        await _bound(nats_client, mock_nats_core, jsm, AsyncMock(), manage_consumer=True)
        jsm.stream_info.assert_awaited_once_with("NOTIFICATIONS_A")
        jsm.add_consumer.assert_awaited_once_with("NOTIFICATIONS_A", config=_spec(manage_consumer=True).consumer_config())

    async def test_a_consumer_that_cannot_be_updated_is_recreated(
        self, nats_client: NATSClient, mock_nats_core: MagicMock, jsm: MagicMock
    ) -> None:
        jsm.add_consumer.side_effect = [APIError(description="consumer already exists"), None]
        await _bound(nats_client, mock_nats_core, jsm, AsyncMock(), manage_consumer=True)
        jsm.delete_consumer.assert_awaited_once_with("NOTIFICATIONS_A", "acme-agent-risk")
        assert jsm.add_consumer.await_count == 2

    async def test_a_missing_stream_is_never_created(self, nats_client: NATSClient, mock_nats_core: MagicMock, jsm: MagicMock) -> None:
        jsm.stream_info.side_effect = NotFoundError()
        with pytest.raises(JetStreamBindingError, match="NOTIFICATIONS_A"):
            await _bound(nats_client, mock_nats_core, jsm, AsyncMock(), manage_consumer=True)
        jsm.add_consumer.assert_not_awaited()
        mock_nats_core.subscribe.assert_not_awaited()


class TestDelivery:
    async def test_the_handler_sees_the_subject_without_the_prefix_and_it_is_acked(
        self, nats_client: NATSClient, mock_nats_core: MagicMock, jsm: MagicMock, cloud_event: CloudEvent
    ) -> None:
        """Settled although the agent's own nats_use_jetstream is off: a binding is always JetStream."""
        seen: list[str] = []

        async def callback(event: CloudEvent, subject: str) -> None:
            seen.append(subject)

        binding, handler = await _bound(nats_client, mock_nats_core, jsm, callback)
        msg = _delivery(cloud_event)
        await _settled(binding, handler, msg)
        assert seen == ["risk.created"]
        msg.ack.assert_awaited_once()

    async def test_a_delivery_no_subject_covers_is_termed_unprocessed(
        self, nats_client: NATSClient, mock_nats_core: MagicMock, jsm: MagicMock, cloud_event: CloudEvent
    ) -> None:
        callback = AsyncMock()
        binding, handler = await _bound(nats_client, mock_nats_core, jsm, callback)
        msg = _delivery(cloud_event, subject=f"{PREFIX}issue.created")
        await _settled(binding, handler, msg)
        callback.assert_not_awaited()
        msg.term.assert_awaited_once()

    async def test_the_heartbeat_follows_the_bindings_ack_wait(
        self, nats_client: NATSClient, mock_nats_core: MagicMock, jsm: MagicMock, cloud_event: CloudEvent
    ) -> None:
        async def slow(event: CloudEvent, subject: str) -> None:
            await asyncio.sleep(0.1)

        binding, handler = await _bound(nats_client, mock_nats_core, jsm, slow, ack_wait=0.03)
        msg = _delivery(cloud_event)
        await _settled(binding, handler, msg)
        assert msg.in_progress.await_count >= 2

    async def test_exhausted_without_a_dead_letter_subject_is_termed(
        self, nats_client: NATSClient, mock_nats_core: MagicMock, jsm: MagicMock, cloud_event: CloudEvent
    ) -> None:
        mock_nats_core.jetstream = MagicMock()
        binding, handler = await _bound(
            nats_client, mock_nats_core, jsm, AsyncMock(side_effect=RetryableHandlerError(status="failed", reason="not yet")), max_deliver=2
        )
        msg = _delivery(cloud_event, delivered=2)
        await _settled(binding, handler, msg)
        msg.term.assert_awaited_once()
        msg.nak.assert_not_awaited()
        mock_nats_core.jetstream.return_value.publish.assert_not_called()

    async def test_exhausted_with_a_dead_letter_subject_stays_on_its_connection(
        self, nats_client: NATSClient, mock_nats_core: MagicMock, jsm: MagicMock, cloud_event: CloudEvent
    ) -> None:
        js = MagicMock(publish=AsyncMock())
        mock_nats_core.jetstream = MagicMock(return_value=js)
        binding, handler = await _bound(
            nats_client,
            mock_nats_core,
            jsm,
            AsyncMock(side_effect=RetryableHandlerError(status="failed", reason="not yet")),
            max_deliver=2,
            dead_letter_subject=f"{PREFIX}dead-letter",
        )
        msg = _delivery(cloud_event, delivered=2)
        await _settled(binding, handler, msg)
        js.publish.assert_awaited_once()
        assert js.publish.await_args.args[0] == f"{PREFIX}dead-letter"
        msg.term.assert_awaited_once()

    async def test_below_the_limit_a_failure_is_nakd(
        self, nats_client: NATSClient, mock_nats_core: MagicMock, jsm: MagicMock, cloud_event: CloudEvent
    ) -> None:
        binding, handler = await _bound(
            nats_client, mock_nats_core, jsm, AsyncMock(side_effect=RetryableHandlerError(status="failed", reason="not yet")), max_deliver=5
        )
        msg = _delivery(cloud_event, delivered=1)
        await _settled(binding, handler, msg)
        msg.nak.assert_awaited_once()


class TestARefusedSubscription:
    """M4 -- the broker refuses a subscription asynchronously; subscribe() alone made it read as bound."""

    async def test_a_refusal_reported_before_the_round_trip_fails_the_bind(
        self, nats_client: NATSClient, mock_nats_core: MagicMock, jsm: MagicMock
    ) -> None:
        async def refuse() -> None:
            # Lowercased, subject included, as nats-py's parser hands the -ERR line on.
            nats_client._link.permission_errors.append('nats: permissions violation for subscription to "acme.agent.a.risk"')

        mock_nats_core.flush = AsyncMock(side_effect=refuse)
        spec = _spec()
        binding = _Binding(link=nats_client._link, jetstream=spec, topic_callbacks=dict.fromkeys(spec.subjects, AsyncMock()))
        mock_nats_core.jsm = MagicMock(return_value=jsm)
        nats_client._link.nats_client = mock_nats_core

        with pytest.raises(PermissionError, match="acme.agent.A.risk"):
            await nats_client._subscribe_all(binding)

        mock_nats_core.subscribe.return_value.unsubscribe.assert_awaited_once()
        assert binding.subscriptions == []

    async def test_a_refusal_for_another_subject_does_not(self, nats_client: NATSClient, mock_nats_core: MagicMock, jsm: MagicMock) -> None:
        async def refuse_other() -> None:
            nats_client._link.permission_errors.append('nats: permissions violation for publish to "elsewhere"')

        mock_nats_core.flush = AsyncMock(side_effect=refuse_other)
        binding, _ = await _bound(nats_client, mock_nats_core, jsm, AsyncMock())
        assert len(binding.subscriptions) == 1


class TestStatusMessagesInBindingMode:
    """S2 -- a plain subscription receives the consumer's heartbeats and flow control requests."""

    @staticmethod
    def _status(reply: str = "") -> MagicMock:
        msg = MagicMock(data=b"", reply=reply, subject="acme.agent.A.risk", headers={"Status": "100", "Description": "Idle Heartbeat"})
        msg.respond = AsyncMock()
        for name in ("ack", "nak", "term"):
            setattr(msg, name, AsyncMock())
        return msg

    async def test_a_flow_control_request_is_answered_and_never_run(
        self, nats_client: NATSClient, mock_nats_core: MagicMock, jsm: MagicMock
    ) -> None:
        callback = AsyncMock()
        binding, handler = await _bound(nats_client, mock_nats_core, jsm, callback)
        msg = self._status(reply="$JS.FC.NOTIFICATIONS_A.x")

        await _settled(binding, handler, msg)

        msg.respond.assert_awaited_once_with(b"")
        callback.assert_not_awaited()
        msg.term.assert_not_awaited()

    async def test_a_stalled_consumer_reported_by_a_heartbeat_is_answered(
        self, nats_client: NATSClient, mock_nats_core: MagicMock, jsm: MagicMock
    ) -> None:
        callback = AsyncMock()
        binding, handler = await _bound(nats_client, mock_nats_core, jsm, callback)
        msg = self._status()
        msg.headers["Nats-Consumer-Stalled"] = "$JS.FC.NOTIFICATIONS_A.y"

        await _settled(binding, handler, msg)

        mock_nats_core.publish.assert_awaited_once_with("$JS.FC.NOTIFICATIONS_A.y", b"")
        callback.assert_not_awaited()

    async def test_an_idle_heartbeat_is_dropped(self, nats_client: NATSClient, mock_nats_core: MagicMock, jsm: MagicMock) -> None:
        callback = AsyncMock()
        binding, handler = await _bound(nats_client, mock_nats_core, jsm, callback)
        msg = self._status()

        await _settled(binding, handler, msg)

        msg.respond.assert_not_awaited()
        callback.assert_not_awaited()
        msg.term.assert_not_awaited()
