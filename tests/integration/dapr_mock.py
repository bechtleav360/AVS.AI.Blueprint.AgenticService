"""A stand-in for the Dapr sidecar, answering the calls a Blueprint app makes to it.

Standard library only, so it runs from any Python 3.10+ with nothing installed:

    python tests/integration/dapr_mock.py                     # listens on 127.0.0.1:3500
    python tests/integration/dapr_mock.py --port 3500 --host 0.0.0.0

What it answers:

- ``GET  /v1.0/healthz`` and ``/v1.0/healthz/outbound`` -> 204. This is all the framework's
  startup ping and readiness check ask for, so starting this process is what turns a Dapr
  agent's ``/health/ready`` from DOWN to UP.
- ``POST /v1.0/publish/<pubsub>/<topic>`` -> 204. The event is accepted and logged, not
  delivered anywhere: there is no broker behind it.
- anything else -> 404, logged, so a call the mock does not know about is visible.

It does not deliver events to the app and does not read the app's ``/dapr/subscribe``. It is
a sidecar that is *there*, not one that routes.
"""

from __future__ import annotations

import argparse
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging import getLogger

_log = getLogger("dapr_mock")

_HEALTH_PATHS = ("/v1.0/healthz", "/v1.0/healthz/outbound")
_PUBLISH_PREFIX = "/v1.0/publish/"


class DaprMockHandler(BaseHTTPRequestHandler):
    """Answer the sidecar endpoints a Blueprint app calls."""

    def do_GET(self) -> None:  # noqa: N802 -- name fixed by BaseHTTPRequestHandler
        path = self.path.split("?", 1)[0]
        if path in _HEALTH_PATHS:
            _log.debug("health check %s", path)
            self._reply(204)
            return
        self._unknown()

    def do_POST(self) -> None:  # noqa: N802 -- name fixed by BaseHTTPRequestHandler
        path = self.path.split("?", 1)[0]
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if path.startswith(_PUBLISH_PREFIX):
            parts = path[len(_PUBLISH_PREFIX) :].split("/", 1)
            if len(parts) == 2 and all(parts):
                pubsub, topic = parts
                _log.info("published to %s/%s: event id %s (%d bytes)", pubsub, topic, _event_id(body), len(body))
                self._reply(204)
                return
        self._unknown()

    def _unknown(self) -> None:
        _log.warning("not mocked: %s %s", self.command, self.path)
        self._reply(404)

    def _reply(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 -- signature fixed by the base class
        """Route the base class's access log through logging instead of stderr."""
        _log.debug(format, *args)


def _event_id(body: bytes) -> str:
    """Return the event's ``id`` if the body is a JSON object carrying one, else ``"?"``."""
    try:
        payload = json.loads(body)
    except ValueError:
        return "?"
    return str(payload.get("id", "?")) if isinstance(payload, dict) else "?"


def main() -> None:
    parser = argparse.ArgumentParser(description="Dapr sidecar mock for Blueprint demos and tests")
    parser.add_argument("--host", default="127.0.0.1", help="interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=3500, help="Dapr HTTP port (default: 3500)")
    parser.add_argument("--verbose", "-v", action="store_true", help="also log every health check")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s dapr-mock %(message)s")
    server = ThreadingHTTPServer((args.host, args.port), DaprMockHandler)
    _log.info("Dapr sidecar mock listening on http://%s:%d", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
