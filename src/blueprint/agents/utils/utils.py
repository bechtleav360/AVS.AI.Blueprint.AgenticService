import re
from logging import getLogger
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ..config import Config

_log = getLogger(__name__)

DEFAULT_APP_HOST = "0.0.0.0"  # nosec B104 -- a container has to accept traffic from outside itself
"""Address the server binds when ``app_host`` is unset.

Bind-all is the only useful default inside a container: the process cannot know the address of
the interface its traffic arrives on, and the network boundary is the pod or the daemon, not the
listener. Override ``app_host`` to narrow it.
"""

DEFAULT_APP_PORT = 8000
"""Port the server binds when ``app_port`` is unset. One port per process, root-scoped: a group
is one application behind one HTTP server, so a per-agent port could not be bound."""

UVICORN_LOG_LEVELS = frozenset({"critical", "error", "warning", "info", "debug", "trace"})
"""The level names uvicorn accepts, which are not quite the ones :mod:`logging` accepts."""


def camel_to_snake(name: str) -> str:
    """
    Convert a CamelCase class name to snake_case variable name.
    Handles acronyms better by treating sequences of 2+ uppercase letters as a single word.
    """

    # Handle the case of multiple uppercase letters (acronyms) followed by lowercase
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    # Handle the case of a lowercase letter or number followed by an uppercase letter
    s2 = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1)
    # Handle the case of multiple uppercase letters at the end of the string
    s3 = re.sub("([A-Z])([A-Z][a-z])", r"\1_\2", s2)
    return s3.lower()


def parse_bool(value: object, key: str) -> bool:
    """Coerce a config value to a bool, accepting the strings an environment variable delivers.

    Dynaconf returns a real bool for ``key = true`` in a TOML file, but an environment
    override arrives as text, so ``"true"`` has to mean the same thing as ``True``.
    Anything else raises rather than being treated as falsy: a typo that silently disables
    a feature is the failure this exists to prevent.

    Args:
        value: The raw config value.
        key: The config key, used only in the error message.

    Returns:
        The parsed boolean.

    Raises:
        ValueError: If the value is neither a bool nor a recognised boolean string.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1", "yes"):
            return True
        if normalized in ("false", "0", "no"):
            return False
    raise ValueError(f"Config key '{key}' must be a boolean, got {value!r}.")


def uvicorn_log_level(configured: object) -> str:
    """Translate the framework's ``log_level`` into one uvicorn accepts.

    The framework spells levels the way :mod:`logging` does (``"INFO"``); uvicorn wants them
    lower-case and knows one level ``logging`` does not (``"trace"``). An unrecognised value
    falls back to ``"info"`` with a warning rather than raising: this level only decides how
    uvicorn narrates itself, nothing outside the process depends on it, and the application's
    own logging has already been configured from the same key by ``Config.configure_logging``.

    Args:
        configured: The raw ``log_level`` value.

    Returns:
        A level name from :data:`UVICORN_LOG_LEVELS`.
    """
    level = str(configured).strip().lower()
    if level in UVICORN_LOG_LEVELS:
        return level
    _log.warning(
        "log_level %r is not a level uvicorn understands (%s); the server will log at 'info'",
        configured,
        ", ".join(sorted(UVICORN_LOG_LEVELS)),
    )
    return "info"


def run_app(app: "FastAPI", config: "Config") -> None:
    """Serve ``app`` with uvicorn, configured from ``config``.

    This is the one line a project's ``main.py`` needs to become runnable, and it exists so the
    host, port and log level a container is started with come from the same settings tree as
    everything else rather than from a duplicated uvicorn invocation.

    Development (``app_environment = "development"``) differs in two ways: the server logs at
    ``debug``, and it runs a single worker whatever the configuration says. Note what is *not*
    here -- **``reload`` is never enabled**. Auto-reload requires uvicorn to import the
    application itself, so it needs an import string (``"src.main:app"``); it cannot restart an
    object that has already been built. A developer who wants reload runs the uvicorn CLI.

    Config keys read: ``app_host`` (default ``"0.0.0.0"``), ``app_port`` (default ``8000``),
    ``app_environment`` (default ``"development"``), ``log_level`` (default ``"info"``) and
    ``app_workers`` (default ``1``).

    Args:
        app: The application returned by ``AppBuilder.build()``.
        config: The configuration the application was built from.

    Raises:
        ValueError: if ``app_workers`` is greater than 1. See below -- this is deliberate.
    """
    import uvicorn

    environment = str(config.get("app_environment", "development"))
    development = environment == "development"

    host = str(config.get("app_host", DEFAULT_APP_HOST))
    port = int(config.get("app_port", DEFAULT_APP_PORT))
    workers = 1 if development else int(config.get("app_workers", 1))

    # Refused rather than passed through, for two independent reasons.
    #
    # uvicorn cannot honour it here at all: with an application *object* rather than an import
    # string, `workers > 1` makes uvicorn log "You must pass the application as an import string"
    # against its own logger and call sys.exit (uvicorn/main.py:603-607). That is a process that
    # dies before binding a port, with a message naming the wrong setting.
    #
    # And it is the wrong shape for this framework even where it works: every worker is a separate
    # process that builds the application again, so N workers open N transport connections, join
    # the queue group N times and start N in-process scheduler timers. Scaling belongs to replicas,
    # which the queue group and the tick claim are built for.
    if workers > 1:
        raise ValueError(
            f"app_workers is {workers}, and this framework serves one application per process. uvicorn cannot "
            "start multiple workers from an application object -- it needs an import string -- and each worker "
            "would build the application again, opening its own transport connection and starting its own "
            "scheduler timer. Scale with replicas instead, or run 'uvicorn src.main:app --workers N' yourself "
            "and accept that every worker is a separate member of the queue group."
        )

    log_level = "debug" if development else uvicorn_log_level(config.get("log_level", "info"))

    _log.info(
        "Serving '%s' on %s:%d (environment %s, uvicorn log level %s, reload disabled)",
        config.get("app_name"),
        host,
        port,
        environment,
        log_level,
    )
    uvicorn.run(app, host=host, port=port, log_level=log_level, workers=workers, reload=False)
