"""A connection source as a tenant deployment writes one, for test_named_connections.py.

One named connection per tenant, each logging in as that tenant's agent user on the accounts broker
(nats-accounts.conf). Everything per test comes from the process config the factory is called with,
because that is all the framework hands it: ``test_source_url``, ``test_source_prefix`` (keeps
streams and subjects apart between tests), ``test_source_tenants``, ``test_source_unclaimed`` and
``test_source_wrong_password`` (tenants whose connection logs in with a password the broker refuses).
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from nats.js import api as js_api

from blueprint.agents.clients.io.nats_connections import ConnectionSpec, JetStreamBinding

SCOPE: ContextVar[str | None] = ContextVar("integration_tenant_scope", default=None)
"""Set by run_scope inside each run: what a deployment would set for its tenant."""

SOURCES: list["TenantSource"] = []
"""Every source built in this process, so a test can change its connections at runtime."""

PASSWORDS = {
    "agent-a": "agent-a-test-only",
    "agent-a2": "agent-a2-test-only",
    "agent-b": "agent-b-test-only",
}


def stream_for(prefix: str, tenant: str) -> str:
    return f"S_{prefix.upper()}_{tenant}"


def subject_prefix_for(prefix: str, tenant: str) -> str:
    return f"t.{tenant}.{prefix}."


def binding_for(prefix: str, agent: str, subjects: tuple[str, ...], tenant: str) -> JetStreamBinding:
    """The binding of one agent on one tenant: also what the operator creates the consumer from."""
    return JetStreamBinding(
        subjects=subjects,
        stream=stream_for(prefix, tenant),
        durable=f"d-{agent}",
        deliver_subject=f"acme.agent.{tenant}.{agent}",
        deliver_group=agent,
        ack_wait=10.0,
        subject_prefix=subject_prefix_for(prefix, tenant),
        max_deliver=3,
        deliver_policy=js_api.DeliverPolicy.NEW,
    )


class TenantSource:
    """Tenants from the config; the users can be changed at runtime and announced through watch()."""

    def __init__(self, config: Any) -> None:
        self.url = str(config.get("test_source_url"))
        self.prefix = str(config.get("test_source_prefix"))
        self.users = {tenant: f"agent-{tenant.lower()}" for tenant in config.get("test_source_tenants") or []}
        self.unclaimed = tuple(config.get("test_source_unclaimed") or ())
        self.wrong_password = set(config.get("test_source_wrong_password") or ())
        self.notifiers: list[Callable[[], None]] = []
        SOURCES.append(self)

    def claims(self, agent: str, subjects: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(subject for subject in subjects if subject not in self.unclaimed)

    def watch(self, notify: Callable[[], None]) -> None:
        self.notifiers.append(notify)

    def set_users(self, users: dict[str, str]) -> None:
        """Replace the tenants and their users, and tell every client."""
        self.users = dict(users)
        for notify in self.notifiers:
            notify()

    def connections(self) -> dict[str, ConnectionSpec]:
        return {
            tenant: ConnectionSpec(
                name=tenant, url=self.url, user=user, password="wrong-test-only" if tenant in self.wrong_password else PASSWORDS[user]
            )
            for tenant, user in self.users.items()
        }

    def binding(self, agent: str, subjects: tuple[str, ...], connection: ConnectionSpec) -> JetStreamBinding:
        return binding_for(self.prefix, agent, self.claims(agent, subjects), connection.name)

    def validate(self, connection: str, subject: str, event: Any) -> str | None:
        """W17.2 in miniature: connection, subject token and the event's tenantid must agree."""
        token = subject.split(".")[1] if subject.count(".") >= 2 else None
        if token != connection:
            return f"subject tenant {token} is not the connection's"
        claimed = (event.model_extra or {}).get("tenantid")
        if claimed != connection:
            return f"event tenantid {claimed} is not the connection's"
        return None

    def run_scope(self, connection: str) -> Any:
        @contextmanager
        def scope() -> Iterator[None]:
            token = SCOPE.set(connection)
            try:
                yield
            finally:
                SCOPE.reset(token)

        return scope()


def create_source(config: Any) -> TenantSource:
    return TenantSource(config)
