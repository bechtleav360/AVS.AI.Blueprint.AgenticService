"""The container's command: resolve this process's group, build it, and serve it.

``python -m blueprint.agents.entrypoint``. One image for the whole platform, with the group
injected at container start rather than baked in at build time -- so which agents a pod runs is
a deployment decision and changing it is a Deployment edit, not a rebuild.

This module exists to hold the three things ``AppBuilder`` must not: reading the environment,
reading files, and exiting the process. Everything it does is four lines; the rest of the file is
about what happens when one of them fails.

**Why exit rather than raise.** A group that cannot be resolved must stop the process *before the
port is bound* (spec sec. 9.1), so that Kubernetes crash-loops the pod with a readable message
instead of reporting a healthy replica that is silently short one consumer. An uncaught exception
would also exit non-zero, but buries the one line an operator needs under a traceback of
framework internals, so the resolution failures are caught and printed as themselves.

A project keeps its own ``main.py`` if it wants: a standalone deployment is untouched by any of
this, and ``uvicorn src.main:app`` still works exactly as before.
"""

import logging
import sys

from fastapi import FastAPI

from .app_builder import AppBuilder
from .config import Config
from .group_config import GroupConfig, GroupConfigError
from .utils import run_app

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS_FILES = ["settings.toml", ".secrets.toml"]
"""Settings the entry point loads, in Dynaconf's usual order.

Named here rather than left to a default because this module *is* the deployment's entry point:
what it loads is part of the contract with the image, and a project that needs something else
writes its own ``main.py`` rather than discovering that this one guessed.
"""


def build(*, environ: dict[str, str] | None = None) -> tuple[FastAPI, Config]:
    """Resolve the group, build the application, and return it with its configuration.

    Separate from :func:`main` so that the whole startup path is testable without a server and
    without ``sys.exit``: everything that can fail happens here, and ``main`` only decides what
    to do about it.

    Args:
        environ: The environment to resolve the group from, for tests.

    Returns:
        The application and the configuration it was built from.

    Raises:
        GroupConfigError: if the group cannot be resolved or a critical agent cannot be loaded.
    """
    config = Config(settings_files=DEFAULT_SETTINGS_FILES)
    group = GroupConfig.resolve(config, environ=environ)
    app = AppBuilder(config).with_group(group).build()
    return app, config


def main(*, environ: dict[str, str] | None = None) -> int:
    """Serve this process's group, or fail with a message and a non-zero status.

    Returns an exit status rather than calling ``sys.exit`` itself, so that a test can assert on
    the status without catching ``SystemExit`` -- the module-level ``__main__`` guard is what
    turns it into an exit.

    Args:
        environ: The environment to resolve the group from, for tests.

    Returns:
        ``0`` if the server ran and stopped normally, ``1`` if the group could not be started.
    """
    try:
        app, config = build(environ=environ)
    except GroupConfigError as exc:
        # Printed as well as logged: logging is configured by AppBuilder, which may not have run
        # yet, and a container whose group is wrong must say so on stderr whatever state the
        # logging configuration is in.
        print(f"Cannot start: {exc}", file=sys.stderr)  # noqa: T201 -- see above
        logger.error("Cannot start: %s", exc)
        return 1

    run_app(app, config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
