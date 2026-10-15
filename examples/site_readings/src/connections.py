"""The connection source: two named connections, one per site, each its own broker account.

Named in ``settings.toml`` as ``nats_connection_source = "src.connections:create_source"``; the
framework calls :func:`create_source` once per process with the process ``Config``. Everything the
source needs comes from there and from the environment (the password, never from a file):

- ``example_broker_url``: the broker every site's account lives on;
- ``example_sites``: per site, the account user the agent logs in as and its alert threshold.

The framework never learns what a site is. It opens the connections listed here, consumes each
site's subjects through the binding below, asks :meth:`SiteSource.validate` before a delivery runs,
and enters :meth:`SiteSource.run_scope` around every run.
"""

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from blueprint.agents.clients.io.nats_connections import ConnectionSpec, JetStreamBinding

from .sites import SiteSettings, enter_site, leave_site

PASSWORD_ENV = "EXAMPLE_NATS_PASSWORD"
"""The environment variable holding the example broker's password (the same one ``deploy/`` uses)."""

CLAIMED_ROOT = "readings."
"""The subject scheme: every subject under ``readings.`` belongs to the sites, never to the default connection."""


def subject_prefix(site: str) -> str:
    """What a site's subjects carry on the wire: ``site.<name>.readings.recorded``."""
    return f"site.{site}."


def stream_name(site: str) -> str:
    return f"READINGS_{site.upper()}"


def deliver_subject(site: str, agent: str) -> str:
    return f"deliver.{site}.{agent}"


def durable_name(agent: str) -> str:
    return f"{agent}-readings"


class SiteSource:
    """One named connection per configured site."""

    def __init__(self, config: Any) -> None:
        self._url = str(config.get("example_broker_url"))
        self._sites: dict[str, dict[str, Any]] = dict(config.get("example_sites") or {})
        self._password = os.environ.get(PASSWORD_ENV, "")
        if not self._password:
            raise ValueError(f"Set {PASSWORD_ENV}: the password of the example broker's site users.")

    def claims(self, agent: str, subjects: tuple[str, ...]) -> tuple[str, ...]:
        """Every declared subject under ``readings.`` belongs to the sites -- whether a site exists yet or not."""
        return tuple(subject for subject in subjects if subject.startswith(CLAIMED_ROOT))

    def connections(self) -> Mapping[str, ConnectionSpec]:
        return {
            site: ConnectionSpec(name=site, url=self._url, user=str(spec["user"]), password=self._password)
            for site, spec in self._sites.items()
        }

    def binding(self, agent: str, subjects: tuple[str, ...], connection: ConnectionSpec) -> JetStreamBinding | None:
        """The consumer ``deploy/provision.py`` creates for ``agent`` in this site's account."""
        claimed = self.claims(agent, subjects)
        if not claimed:
            return None
        return JetStreamBinding(
            subjects=claimed,
            stream=stream_name(connection.name),
            durable=durable_name(agent),
            deliver_subject=deliver_subject(connection.name, agent),
            deliver_group=agent,
            ack_wait=30.0,
            subject_prefix=subject_prefix(connection.name),
            max_deliver=5,
        )

    def validate(self, connection: str, subject: str, event: Any) -> str | None:
        """A delivery runs only if the wire subject and the event's source both name this connection's site."""
        if not subject.startswith(subject_prefix(connection)):
            return f"subject {subject!r} is not under {subject_prefix(connection)!r}"
        if event.source != f"/sites/{connection}":
            return f"event source {event.source!r} is not /sites/{connection}"
        return None

    def run_scope(self, connection: str) -> Any:
        """Open the site's settings around the run: the threshold the service applies."""
        settings = SiteSettings(name=connection, alert_threshold=float(self._sites[connection]["alert_threshold"]))

        @contextmanager
        def scope() -> Iterator[None]:
            token = enter_site(settings)
            try:
                yield
            finally:
                leave_site(token)

        return scope()


def create_source(config: Any) -> SiteSource:
    """The factory ``nats_connection_source`` names."""
    return SiteSource(config)
