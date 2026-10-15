"""What the deployment owns, done once per site: the stream and the agent's consumer.

The agent never creates either (its users may only receive and acknowledge). Run after the broker
is up; reads EXAMPLE_NATS_PASSWORD and the same settings the source reads::

    python deploy/provision.py [--publish]

``--publish`` also sends one reading below and one above each site's threshold.
"""

import asyncio
import json
import os
import sys
import tomllib
import uuid
from pathlib import Path

import nats

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.connections import SiteSource, stream_name, subject_prefix  # noqa: E402


class _Settings:
    """The two keys the source reads, from settings.toml, without starting the framework."""

    def __init__(self) -> None:
        self._values = tomllib.loads((ROOT / "settings.toml").read_text(encoding="utf-8"))["default"]

    def get(self, key: str, default: object = None) -> object:
        return self._values.get(key, default)


async def provision(publish: bool) -> None:
    settings = _Settings()
    source = SiteSource(settings)
    agent = str(settings.get("app_name"))
    password = os.environ["EXAMPLE_NATS_PASSWORD"]
    for site, spec in source.connections().items():
        admin = await nats.connect(spec.url, user=f"admin-{site.replace('_', '-')}", password=password)
        jsm = admin.jsm()
        await jsm.add_stream(name=stream_name(site), subjects=[f"{subject_prefix(site)}>"])
        binding = source.binding(agent, ("readings.>",), spec)
        if binding is None:
            raise SystemExit(f"{site}: the source binds nothing for readings.> -- check src/connections.py")
        await jsm.add_consumer(binding.stream, config=binding.consumer_config())
        print(f"{site}: stream {binding.stream}, consumer {binding.durable} -> {binding.deliver_subject}")
        if publish:
            threshold = float(settings.get("example_sites")[site]["alert_threshold"])  # type: ignore[index]
            for value in (threshold - 1, threshold + 1):
                event = {
                    "specversion": "1.0",
                    "id": str(uuid.uuid4()),
                    "type": "reading.recorded",
                    "source": f"/sites/{site}",
                    "data": {"sensor_id": f"{site}-s1", "value": value},
                }
                await admin.jetstream().publish(f"{subject_prefix(site)}readings.recorded", json.dumps(event).encode())
            print(f"{site}: published {threshold - 1} and {threshold + 1}")
        await admin.close()


if __name__ == "__main__":
    asyncio.run(provision("--publish" in sys.argv))
