"""Validate command - check project structure and configuration.

Every check that predicts a startup failure or a startup warning reads the settings the way the
process does, for one target environment, and applies the runtime's own rule wherever the runtime
has one as a public function. The project's own code is never imported: files are read and parsed.
"""

import ast
import importlib.util
import logging
import os
import sys
import tomllib
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dynaconf import Dynaconf

from blueprint.agents.clients.io.io_client_base import TOPIC_TRANSPORTS, validate_subject_segment
from blueprint.agents.clients.io.nats_client import CONNECTIONS_READINESS_MODES
from blueprint.agents.clients.io.nats_run_pool import RunLimit
from blueprint.agents.config.config import (
    AGENT_REFUSED_KEYS,
    DEFAULT_ENVVAR_PREFIX,
    DEFAULT_SETTINGS_FILES,
    Config,
    ConfigError,
    environment_section_names,
    layer_settings_document,
)
from blueprint.agents.io.api.scheduling.scheduler import (
    SCHEDULER_MODE_EVENT,
    SCHEDULER_MODE_IN_PROCESS,
    SCHEDULER_MODES,
    delivers_ticks,
    normalise_scheduler_mode,
    validate_crontab,
)
from blueprint.agents.utils import parse_bool

from ..utils.cancellation_check import swallowed_cancellation_warning, swallowed_cancellations

logger = logging.getLogger(__name__)

AGENT_MAP_FILE = "agents.toml"
SETTINGS_FILE = "settings.toml"
SECRETS_FILE = ".secrets.toml"

DEFAULT_ENVIRONMENT = "production"
"""The environment checked when neither ``--environment`` nor the environment names one.

Both scaffolded Dockerfiles set ``DYNACONF_APP_ENVIRONMENT="production"`` in the image that is
deployed, so that is the section a pod loads -- not the ``development`` the framework defaults to
when nothing sets it.
"""

EVENT_BUSES = (*TOPIC_TRANSPORTS, "sessions")
"""The ``event_bus`` values ``AppBuilder`` wires a transport for; anything else disables event handling."""

READ_AT_THE_TOP_LEVEL = frozenset({"envvar_prefix", "app_environment", "dynaconf_merge", "dynaconf_include"})
"""Keys the process does read outside any section: the bootstrap pass reads these from the top level."""

IDEMPOTENCY_NOTICE = "\n".join(
    [
        "Event deduplication is off ('idempotency_enabled' is not set), so every handler in",
        "    this project can be run more than once for the same event. Delivery is at-least-once:",
        "    a lost acknowledgement, a pod restart or a rolling deploy each produce a redelivery,",
        "    after the first attempt has already committed its side effects.",
        "    Decide which one this project needs:",
        "      - handlers that are safe to repeat -- nothing to change; or",
        "      - set 'idempotency_enabled = true' and 'idempotency_ttl = <seconds>' in settings.toml,",
        "        with a window that outlasts the broker redelivery window, and add .with_cache() to",
        "        the AppBuilder chain: the markers are kept in this agent's cache.",
    ]
)

Findings = tuple[list[str], list[str], list[str]]
"""Issues, warnings and notices, in that order."""


# ----------------------------------------------------------------------------------------------
# Settings, read the way the process reads them
# ----------------------------------------------------------------------------------------------


def _lookup(source: Any, key: str) -> Any | None:
    """``key`` (dotted for a nested table) in ``source``, matched case-insensitively; ``None`` when absent."""
    node = source
    for part in key.split("."):
        if not isinstance(node, dict):
            return None
        match = next((value for name, value in node.items() if str(name).lower() == part.lower()), None)
        if match is None:
            return None
        node = match
    return node


def _plain(value: Any) -> Any:
    """A Dynaconf box as plain dicts and lists, so nothing downstream depends on Dynaconf's types."""
    if hasattr(value, "items"):
        return {str(key): _plain(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(inner) for inner in value]
    return value


@dataclass(frozen=True)
class SettingsView:
    """What one namespace reads: its own scope first, then the process's root keys.

    ``sources`` is in precedence order and the first that sets a key wins, with ``None`` meaning
    "not set" -- the resolution ``Config.get`` performs for a scoped view, where the scope holds
    the image's ``[default.<agent>]`` and environment overrides, then the agent's ``.secrets.toml``,
    then its ``settings.toml`` (the merge fills in what is missing), and the root tree comes last.
    """

    sources: tuple[dict[str, Any], ...]

    def get(self, key: str, default: Any = None) -> Any:
        """``key``'s value as this namespace reads it, or ``default``."""
        for source in self.sources:
            value = _lookup(source, key)
            if value is not None:
                return value
        return default


@dataclass(frozen=True)
class ProcessSettings:
    """The process's own settings files (``settings.toml`` and ``.secrets.toml``), loaded for one environment.

    Loaded through Dynaconf in environment mode, with the prefix the runtime resolves
    (``Config.resolve_envvar_prefix``), so the layering is the process's own: ``[default]``, the
    target environment's section and ``[global]``, plus every environment override in this
    process's environment. A key written outside any section, or only in another environment's
    section, is therefore not set -- as it is not for the pod.

    ``app_environment`` is set to the target environment, as the Dockerfiles' environment variable
    sets it for the pod.

    Attributes:
        directory: The directory the files were read from.
        environment: The environment checked.
        prefix: The environment-override prefix, or ``False`` for none.
        tree: The loaded tree, top-level keys lower-cased.
        documents: The files as parsed, for the keys they spell.
        problems: What stopped the files being read, as issues.
    """

    directory: Path
    environment: str
    prefix: str | bool
    tree: dict[str, Any]
    documents: dict[str, dict[str, Any]]
    problems: tuple[str, ...]

    @classmethod
    def load(cls, directory: Path, environment: str | None = None) -> "ProcessSettings":
        """Read the process's settings in ``directory`` for ``environment``.

        Args:
            directory: The project or image root.
            environment: ``--environment``. Unset, the environment variable the process reads
                (``<prefix>_APP_ENVIRONMENT``) decides, and without one :data:`DEFAULT_ENVIRONMENT`.
        """
        files = [directory / name for name in DEFAULT_SETTINGS_FILES if (directory / name).is_file()]
        documents: dict[str, dict[str, Any]] = {}
        problems: list[str] = []
        for path in files:
            try:
                documents[path.name] = tomllib.loads(path.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError) as exc:
                # Values are never shown, so an unparseable secrets file is named, not quoted.
                problems.append(f"{path.name} could not be read: {exc}")
        if problems:
            # Guessing at a key from a file that does not parse would be worse than staying quiet.
            return cls(
                directory, cls._environment(environment, DEFAULT_ENVVAR_PREFIX), DEFAULT_ENVVAR_PREFIX, {}, documents, tuple(problems)
            )

        names = [str(path) for path in files]
        bootstrap = Dynaconf(settings_files=names, environments=False, load_dotenv=False, merge_enabled=True)
        try:
            prefix = Config.resolve_envvar_prefix(bootstrap)
        except ConfigError as exc:
            problems.append(str(exc))
            prefix = DEFAULT_ENVVAR_PREFIX
        target = cls._environment(environment, prefix)
        loaded = Dynaconf(settings_files=names, environments=True, env=target, load_dotenv=False, merge_enabled=True, envvar_prefix=prefix)
        tree = {str(key).lower(): _plain(value) for key, value in loaded.as_dict().items()}
        tree["app_environment"] = target
        return cls(directory, target, prefix, tree, documents, tuple(problems))

    @staticmethod
    def _environment(requested: str | None, prefix: str | bool) -> str:
        """The target environment: the option, else the process's environment variable, else production."""
        variables = ([f"{prefix}_APP_ENVIRONMENT"] if prefix and prefix != DEFAULT_ENVVAR_PREFIX else []) + [
            f"{DEFAULT_ENVVAR_PREFIX}_APP_ENVIRONMENT"
        ]
        for candidate in [requested, *(os.environ.get(name) for name in variables)]:
            if candidate and candidate.strip():
                return candidate.strip().lower()
        return DEFAULT_ENVIRONMENT

    @property
    def readable(self) -> bool:
        """Whether every settings file parsed; checks that read values stay quiet otherwise."""
        return not self.problems

    @property
    def override_variable_prefix(self) -> str:
        """How an environment override is spelled: ``DYNACONF_`` or the declared prefix, or nothing."""
        return f"{self.prefix}_" if self.prefix else ""

    def root_view(self) -> SettingsView:
        """What the root namespace -- a standalone agent, or the process itself -- reads."""
        return SettingsView((self.tree,))

    def environment_names(self) -> frozenset[str]:
        """The table names that are environment sections to this process (the runtime's own rule)."""
        return environment_section_names(list(self.documents.values()))

    def layered(self, document: dict[str, Any]) -> dict[str, Any]:
        """An agent's file flattened for this environment, as ``Config.merge_agent_settings`` flattens it."""
        return layer_settings_document(document, self.environment, self.environment_names())

    def agent_view(self, name: str, fragments: list[dict[str, Any]]) -> SettingsView:
        """What agent ``name`` reads, given its own files already parsed (``.secrets.toml`` first).

        The keys the merge drops (:data:`AGENT_REFUSED_KEYS`) are dropped here too, so such a key
        resolves to the process's value -- which is what the agent then reads.
        """
        scope = _lookup(self.tree, name)
        own = [scope] if isinstance(scope, dict) else []
        kept = [
            {key: value for key, value in self.layered(document).items() if str(key).lower() not in AGENT_REFUSED_KEYS}
            for document in fragments
        ]
        return SettingsView((*own, *kept, self.tree))

    def unread_key_warnings(self) -> list[str]:
        """Keys written at the top level of the process's own files, where the process loads nothing.

        In environment mode Dynaconf loads ``[default]``, the active environment's section and
        ``[global]``; a plain key above them is read by nobody (verified against dynaconf 3.3.5).
        Keys only, never values: one of these files holds secrets.
        """
        warnings = []
        for file_name, document in self.documents.items():
            unread = sorted(
                str(key) for key, value in document.items() if not isinstance(value, dict) and str(key).lower() not in READ_AT_THE_TOP_LEVEL
            )
            if unread:
                warnings.append(
                    f"{file_name} sets {', '.join(unread)} at the top level, outside any section. The process loads "
                    "[default], the active environment's section and [global] only, so nothing reads them. Move them "
                    "under [default]."
                )
        return warnings


def read_document(path: Path) -> dict[str, Any] | None:
    """A parsed TOML file, or ``None`` when it is missing or unreadable (its own check reports that)."""
    if not path.is_file():
        return None
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.debug("Could not read %s: %s", path, exc)
        return None


# ----------------------------------------------------------------------------------------------
# The command
# ----------------------------------------------------------------------------------------------


def run(args: Namespace) -> None:
    """Execute the validate command.

    Args:
        args: Parsed command-line arguments
    """
    from . import validate_group  # here, not at the top: validate_group imports this module

    # An image and an agent are different things to check, so this is a mode rather than a
    # guess about what the directory looks like.
    if getattr(args, "group", False):
        validate_group.run(args)
        return

    project_dir = Path(args.project_dir).resolve()

    if not project_dir.is_dir():
        print(f"Error: Project directory does not exist: {project_dir}", file=sys.stderr)
        sys.exit(1)

    settings = ProcessSettings.load(project_dir, getattr(args, "environment", None))
    print(f"Validating Blueprint Agents project: {project_dir}")
    print(f"Environment: {settings.environment} (choose another with --environment)")
    print()

    issues: list[str] = []
    warnings: list[str] = []
    notices: list[str] = []

    for dir_name in ("src", "tests"):
        if not (project_dir / dir_name).is_dir():
            issues.append(f"Missing required directory: {dir_name}/")
        else:
            print(f"[ok] Found {dir_name}/")

    for file_name in (SETTINGS_FILE, "pyproject.toml"):
        if not (project_dir / file_name).is_file():
            issues.append(f"Missing configuration file: {file_name}")
        else:
            print(f"[ok] Found {file_name}")

    # The leading dot is what DEFAULT_SETTINGS_FILES names, so a file without it is loaded by
    # nothing -- which is why an undotted one is reported as the rename it needs rather than as a
    # file that is simply missing.
    if not (project_dir / ".secrets.toml.example").is_file():
        warnings.append("Missing .secrets.toml.example template")
    else:
        print("[ok] Found .secrets.toml.example")
    if not (project_dir / SECRETS_FILE).is_file():
        if (project_dir / "secrets.toml").is_file():
            warnings.append(
                "Found secrets.toml, which nothing loads: the framework reads '.secrets.toml'. "
                "Rename it (git mv secrets.toml .secrets.toml) or its keys are invisible at startup."
            )
        else:
            warnings.append("Missing .secrets.toml (copy from .secrets.toml.example)")

    main_file = project_dir / "src" / "main.py"
    if not main_file.is_file():
        issues.append("Missing src/main.py entry point")
    else:
        print("[ok] Found src/main.py")
        # Nothing is checked about Config here: main.py is a declaration, and the configuration
        # belongs to whatever builds it.
        if "AppBuilder" not in main_file.read_text(encoding="utf-8"):
            warnings.append("src/main.py does not appear to use AppBuilder")

    src_dir = project_dir / "src"
    if src_dir.is_dir():
        for dir_name in ("handlers", "services", "api", "models"):
            if (src_dir / dir_name).is_dir():
                print(f"[ok] Found src/{dir_name}/")

    tests_dir = project_dir / "tests"
    if tests_dir.is_dir():
        test_files = list(tests_dir.glob("test_*.py"))
        if not test_files:
            warnings.append("No test files found in tests/")
        else:
            print(f"[ok] Found {len(test_files)} test file(s)")

    if (project_dir / "Dockerfile").is_file():
        print("[ok] Found Dockerfile")
    else:
        warnings.append("Missing Dockerfile for containerization")
    if (project_dir / "docker-compose.yml").is_file():
        print("[ok] Found docker-compose.yml")

    # A swallowed cancellation defeats nats_handler_timeout: the run goes on and is nak'd anyway.
    if src_dir.is_dir():
        swallowed = swallowed_cancellations(src_dir)
        if swallowed:
            warnings.append(swallowed_cancellation_warning(project_dir.name, swallowed))

    issues.extend(settings.problems)
    warnings.extend(settings.unread_key_warnings())

    # A project holding an agent map with entries is an image, and its agents are checked as the
    # group entry point would host them; otherwise the project is the process, at the root.
    group_issues, group_warnings, group_notices = _group_findings(project_dir, settings.environment)
    issues.extend(group_issues)
    warnings.extend(group_warnings)
    notices.extend(group_notices)
    if not _hosts_agents(project_dir):
        root_issues, root_warnings, root_notices = root_findings(project_dir, settings)
        issues.extend(root_issues)
        warnings.extend(root_warnings)
        notices.extend(root_notices)

    print()
    print("=" * 60)

    if notices:
        print(f"\nNotices ({len(notices)}):")
        for item in notices:
            print(f"  - {item}")

    if not issues and not warnings:
        print("[ok] Validation passed! Project structure looks good.")
        sys.exit(0)

    if warnings:
        print(f"\nWarnings ({len(warnings)}):")
        for warning in warnings:
            print(f"  - {warning}")

    if issues:
        print(f"\nIssues ({len(issues)}):")
        for issue in issues:
            print(f"  - {issue}")
        print("\nProject validation failed. Please fix the issues above.")
        sys.exit(1)
    else:
        print("\n[ok] Validation passed with warnings.")
        sys.exit(0)


def root_findings(project_dir: Path, settings: ProcessSettings) -> Findings:
    """Everything the process checks at startup for a standalone agent, which runs at the root namespace.

    Args:
        project_dir: The project root, which is also the process's directory.
        settings: The project's settings, loaded for the target environment.
    """
    if not settings.readable:
        return [], [], []
    view = settings.root_view()
    issues: list[str] = []
    warnings: list[str] = []
    notices: list[str] = []

    # Idempotency decision (spec sec. 7.4): the framework must not choose for the author, so it
    # says nothing at all only when the project has no handlers to run twice.
    if has_handlers(project_dir) and view.get("idempotency_enabled") is None:
        notices.append(IDEMPOTENCY_NOTICE)

    for found in (
        scheduler_findings(project_dir, view=view, settings=settings, where=SETTINGS_FILE),
        dedup_findings(project_dir, view=view, settings=settings),
        transport_findings(project_dir, view=view, settings=settings),
        process_findings(settings),
    ):
        issues.extend(found[0])
        warnings.extend(found[1])
        notices.extend(found[2])
    issues.extend(nats_value_findings(project_dir, view))
    return issues, warnings, notices


def _idempotency_notice(project_dir: Path, environment: str | None = None) -> str | None:
    """Return the dedup notice if this project has handlers and has not decided on dedup.

    ``None`` when ``idempotency_enabled`` is set either way for the target environment -- the
    author has then made the decision spec sec. 7.4 asks for -- when there are no handlers, and
    when the settings cannot be read (that has its own report).
    """
    if not has_handlers(project_dir):
        return None
    settings = ProcessSettings.load(project_dir, environment)
    if not settings.readable:
        return None
    return IDEMPOTENCY_NOTICE if settings.root_view().get("idempotency_enabled") is None else None


# ----------------------------------------------------------------------------------------------
# Group readiness
#
# There is deliberately no `asbs migrate` -- main.py is the developer's own declaration, and a
# tool that rewrites it either guesses at intent or fails on anything hand-edited. A checklist
# plus a validate that names what is missing is the honest shape.
# ----------------------------------------------------------------------------------------------

NO_AGENT_MAP_NOTICE = "\n".join(
    [
        "No agents.toml here, which is right for an agent: the map says which agents an *image*",
        "    contains, so it belongs to the image that hosts this agent, never to the agent itself.",
        "    Served on its own, the agent needs none. To host it in a group, add one entry to the",
        "    image's agents.toml ([agents.<name>] with root and module) and check the image with",
        "    'asbs validate --group' -- see 'asbs docs guides/multi-agent-migration'. The name chosen",
        "    there becomes the queue group, part of the durable name and the /api/<name> prefix, so",
        "    it is a consumer migration to change after the first deploy.",
    ]
)


def _hosts_agents(project_dir: Path) -> bool:
    """Whether ``project_dir`` holds an agent map with entries, which makes it an image."""
    document = read_document(project_dir / AGENT_MAP_FILE)
    declared = document.get("agents") if document else None
    return isinstance(declared, dict) and bool(declared)


def _group_findings(project_dir: Path, environment: str | None = None) -> Findings:
    """Report what the project's agent map says, if it has one.

    No map is the right shape for an agent, and gets a notice. A map with entries makes this
    directory an image, so it is checked by ``asbs validate --group``'s own rules -- each entry
    needs a ``root`` and the agent's settings are read from beside that root's ``src``, as at
    runtime -- rather than by a second, older reading of the same file.

    Args:
        project_dir: The project root.
        environment: The target environment.
    """
    from . import validate_group  # here, not at the top: validate_group imports this module

    agent_map = project_dir / AGENT_MAP_FILE
    if not agent_map.is_file():
        return [], [], [NO_AGENT_MAP_NOTICE]
    try:
        tomllib.loads(agent_map.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [f"{AGENT_MAP_FILE} could not be read: {exc}"], [], []
    if not _hosts_agents(project_dir):
        return [f"{AGENT_MAP_FILE} declares no [agents.<name>] entries, so this image contains no agents"], [], []
    print(f"[ok] {AGENT_MAP_FILE} declares agents, so this directory is checked as an image (asbs validate --group)")
    return validate_group.image_findings(project_dir, agent_map, environment=environment)


# ----------------------------------------------------------------------------------------------
# The runtime's startup checks, for one namespace
# ----------------------------------------------------------------------------------------------


def has_handlers(agent_dir: Path) -> bool:
    """Whether the agent registers event handlers (scaffolded as ``src/handlers/*_handler.py``)."""
    handlers_dir = agent_dir / "src" / "handlers"
    return handlers_dir.is_dir() and any(handlers_dir.glob("*_handler.py"))


def scheduler_modules(agent_dir: Path) -> list[Path]:
    """Return the scheduler modules this agent defines."""
    schedulers_dir = agent_dir / "src" / "schedulers"
    if not schedulers_dir.is_dir():
        return []
    return [path for path in sorted(schedulers_dir.glob("*.py")) if path.name != "__init__.py"]


def main_declares_a_cache(agent_dir: Path) -> bool:
    """Report whether the declaration registers a cache (read, not imported)."""
    main_file = agent_dir / "src" / "main.py"
    return main_file.is_file() and ".with_cache(" in main_file.read_text(encoding="utf-8")


def declared_crontabs(path: Path) -> list[str]:
    """The literal crontabs a scheduler module hands ``SchedulerBase.__init__``.

    Parsed rather than imported: ``crontab="..."`` as a keyword anywhere, or a string as the first
    argument of an ``__init__`` call. A crontab computed at runtime is not seen, and not reported.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == "crontab" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                found.append(keyword.value.value)
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "__init__"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            found.append(node.args[0].value)
    return found


def literal_topics(agent_dir: Path) -> list[str] | None:
    """The topics the agent's handlers declare, when every declaration is a literal list.

    ``None`` when any ``get_subscribed_topics`` returns something other than a list or tuple of
    strings: the topics are then only known at runtime, and a check built on them would guess.
    """
    handlers_dir = agent_dir / "src" / "handlers"
    if not handlers_dir.is_dir():
        return []
    topics: dict[str, None] = {}
    for path in sorted(handlers_dir.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            return None
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name != "get_subscribed_topics":
                continue
            for returned in (inner for inner in ast.walk(node) if isinstance(inner, ast.Return)):
                value = returned.value
                if not isinstance(value, (ast.List, ast.Tuple)) or not all(
                    isinstance(item, ast.Constant) and isinstance(item.value, str) for item in value.elts
                ):
                    return None
                for item in value.elts:
                    if isinstance(item, ast.Constant) and item.value:
                        topics[str(item.value)] = None
    return list(topics)


def _bus(settings: ProcessSettings) -> str:
    """``event_bus`` as ``AppBuilder`` reads it: the process's value, trimmed and lower-cased."""
    return str(settings.root_view().get("event_bus", "") or "").strip().lower()


def _mode(view: SettingsView) -> str:
    return normalise_scheduler_mode(view.get("scheduler_mode"))


def consumes_events(agent_dir: Path, view: SettingsView) -> bool:
    """Whether the agent has an event handler: one of its own, or an event-mode scheduler's tick handler."""
    return has_handlers(agent_dir) or (bool(scheduler_modules(agent_dir)) and _mode(view) == SCHEDULER_MODE_EVENT)


def scheduler_findings(agent_dir: Path, *, view: SettingsView, settings: ProcessSettings, where: str, agent: str = "") -> Findings:
    """The scheduler checks, on the runtime's own terms; shared by the single and the group command.

    ``scheduler_mode`` has no default and fails at ``build()`` when a scheduler is registered
    without it. The half that fails *nowhere* is the reason this check exists: ``"event"`` mode
    starts no timer and waits for a tick that an external ``CronJob`` must publish, and nothing in
    this repository generates one. Each literal crontab is checked with ``validate_crontab`` in
    the resolved mode, and ``scheduler_timezone`` as the in-process timer reads it.

    Args:
        agent_dir: The directory whose ``src/schedulers`` is looked at.
        view: What this namespace reads; ``scheduler_mode`` comes from here.
        settings: The process's settings; ``event_bus`` is a process key.
        where: The file(s) named in a message.
        agent: The agent's name in a group, for the messages.
    """
    schedulers = scheduler_modules(agent_dir)
    if not schedulers:
        return [], [], []
    named = f"Agent '{agent}': " if agent else ""

    raw_mode = view.get("scheduler_mode")
    mode = normalise_scheduler_mode(raw_mode)
    if not mode:
        return (
            [
                f"{named}{len(schedulers)} scheduler(s) under src/schedulers/ and no 'scheduler_mode' in {where} or the "
                f"environment for '{settings.environment}'. It has no default, because neither value is safe to inherit, "
                f"so build() fails: set '{SCHEDULER_MODE_IN_PROCESS}' to run a timer in the process (needs .with_cache(), "
                f"and a Redis cache once there is more than one replica) or '{SCHEDULER_MODE_EVENT}' to take the tick as an "
                "event (needs 'event_bus', and something publishing it)"
            ],
            [],
            [],
        )
    if mode not in SCHEDULER_MODES:
        return [f"{named}'scheduler_mode' is {raw_mode!r}; it must be one of {', '.join(SCHEDULER_MODES)}"], [], []

    issues: list[str] = []
    notices: list[str] = []
    for path in schedulers:
        for crontab in declared_crontabs(path):
            try:
                validate_crontab(crontab, mode)
            except ValueError as exc:
                issues.append(f"{named}{path.relative_to(agent_dir).as_posix()}: {exc}")

    if mode == SCHEDULER_MODE_EVENT:
        # A notice, not an issue: nothing here can tell whether a CronJob exists.
        notices.append(
            "\n".join(
                [
                    f"{named}'scheduler_mode' is '{SCHEDULER_MODE_EVENT}', so no timer runs in this process: each tick",
                    "    arrives as an event on '<agent>.scheduler.<scheduler name>', published by an external",
                    "    CronJob. Nothing in this project generates that CronJob, and a scheduler waiting for a",
                    "    tick nobody publishes reports itself healthy and never runs. Confirm one exists, on the",
                    "    schedule the scheduler declares, for every scheduler under src/schedulers/.",
                ]
            )
        )
        bus = _bus(settings)
        if not bus:
            # A notice: event_bus is a process key, and the deployment's environment may set it.
            notices.append(
                f"{named}'scheduler_mode' is '{SCHEDULER_MODE_EVENT}' and no 'event_bus' is set for "
                f"'{settings.environment}' in {where} or the environment. The tick arrives as an event, so startup "
                "fails unless the process sets one of 'dapr' or 'nats'."
            )
        elif not delivers_ticks(bus):
            issues.append(
                f"{named}'scheduler_mode' is '{SCHEDULER_MODE_EVENT}' and 'event_bus' is {bus!r}, which cannot deliver "
                "a tick: the tick is an event on a topic, so it needs 'dapr' or 'nats'. Wiring the scheduler fails at "
                "startup"
            )
        return issues, [], notices

    # In process: the timer reads scheduler_timezone, as SchedulerBase reads it at startup.
    timezone = str(view.get("scheduler_timezone", "") or "").strip()
    if timezone:
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            issues.append(
                f"{named}'scheduler_timezone' is {timezone!r}, which is not an IANA timezone name (such as "
                "'Europe/Berlin' or 'UTC'). Every in-process scheduler fails to start"
            )
    if not main_declares_a_cache(agent_dir):
        notices.append(
            "\n".join(
                [
                    f"{named}'scheduler_mode' is '{SCHEDULER_MODE_IN_PROCESS}' and src/main.py declares no cache.",
                    "    Each tick is claimed in the agent's own cache; with no cache to claim in,",
                    '    every replica runs every tick. Add .with_cache() -- with cache.backend = "redis"',
                    "    once there is more than one replica -- unless this runs as a single replica.",
                ]
            )
        )
    else:
        notice = _disk_claim_notice(view, named, "each in-process scheduler tick")
        if notice:
            notices.append(notice)
    return issues, [], notices


def _disk_claim_notice(view: SettingsView, named: str, what: str) -> str | None:
    """Say that a claim on a disk cache holds within one process, when the cache is not Redis."""
    backend = str(view.get("cache.backend", "disk") or "disk").strip().lower()
    if backend == "redis":
        return None
    return "\n".join(
        [
            f"{named}The cache backend is {backend!r}, and {what} is claimed in it. A disk cache's claim",
            "    holds within one process only: replicas sharing its directory can each win the same claim.",
            '    Set cache.backend = "redis" before running more than one replica.',
        ]
    )


def dedup_findings(agent_dir: Path, *, view: SettingsView, settings: ProcessSettings, agent: str = "") -> Findings:
    """The dedup policy a handler chain resolves at startup, and the warnings it logs.

    The rules of ``HandlerChain._resolve_idempotency_policy`` and ``_warn_without_a_heartbeat``,
    in their own words. Neither is public, and both live in the runtime, so they are restated here
    and pinned by tests; the boolean is read with the runtime's ``parse_bool``.
    """
    if not consumes_events(agent_dir, view):
        return [], [], []
    named = f"Agent '{agent}': " if agent else ""
    try:
        enabled = parse_bool(view.get("idempotency_enabled", False), "idempotency_enabled")
    except ValueError as exc:
        return [f"{named}{exc}"], [], []
    if not enabled:
        return [], [], []

    issues: list[str] = []
    raw_ttl = view.get("idempotency_ttl")
    if raw_ttl is None:
        issues.append(
            f"{named}'idempotency_enabled' is true but 'idempotency_ttl' is not set. It is the number of seconds a "
            "processed event is remembered, and it must outlast the broker's redelivery window ('nats_ack_wait' * "
            "'nats_max_deliver' on JetStream). Startup fails"
        )
    else:
        try:
            ttl = int(raw_ttl)
        except (TypeError, ValueError):
            issues.append(f"{named}Config key 'idempotency_ttl' must be an integer number of seconds, got {raw_ttl!r}.")
        else:
            if ttl <= 0:
                issues.append(f"{named}'idempotency_ttl' must be greater than 0, got {ttl}. It is the dedup window, in seconds.")
    if not main_declares_a_cache(agent_dir):
        issues.append(
            f"{named}'idempotency_enabled' is true but src/main.py declares no cache, so there is nowhere to record "
            "the events already processed. Add '.with_cache()' to the AppBuilder chain. Startup fails"
        )

    warnings: list[str] = []
    bus = _bus(settings)
    label = agent or "<root>"
    if bus == "nats" and view.get("nats_heartbeat_enabled", True) is False:
        warnings.append(
            f"Agent '{label}' deduplicates events with 'nats_heartbeat_enabled = false': a run that outlasts ack_wait "
            "is redelivered while it runs, the redelivery is skipped as a duplicate and acknowledged, and if the first "
            "run then fails the event is lost. Keep the heartbeat on, or keep runs well under ack_wait."
        )
    elif bus == "dapr":
        warnings.append(
            f"Agent '{label}' deduplicates events under Dapr, which has no heartbeat: a run that outlasts the sidecar's "
            "app-call timeout is delivered again while it runs, that delivery is skipped as a duplicate, and if the "
            "first run then fails the event is lost. Keep runs well under that timeout."
        )

    notices: list[str] = []
    if main_declares_a_cache(agent_dir):
        notice = _disk_claim_notice(view, named, "each event's dedup marker")
        if notice:
            notices.append(notice)
    return issues, warnings, notices


def transport_findings(agent_dir: Path, *, view: SettingsView, settings: ProcessSettings, agent: str = "") -> Findings:
    """What wiring this agent's transport refuses or warns about at startup.

    Handlers with no usable ``event_bus`` (a WARNING from ``AppBuilder``); and, under NATS, for an
    agent that has a client: an unset ``nats_url`` outside development, a non-boolean
    ``nats_heartbeat_enabled``, one ``nats_durable_name`` for several topics and -- at the root
    namespace, where the queue group is not the agent's name -- a queue group that cannot appear
    in a subject (checked with the runtime's ``validate_subject_segment``).
    """
    named = f"Agent '{agent}': " if agent else ""
    bus = _bus(settings)
    warnings: list[str] = []
    if has_handlers(agent_dir) and bus not in EVENT_BUSES:
        where = f"Namespace '{agent}' has" if agent else "This project has"
        warnings.append(
            f"{where} event handlers registered but no valid event_bus is configured for '{settings.environment}' "
            f"({', '.join(repr(name) for name in EVENT_BUSES)}). Event handling will be disabled -- the runtime only "
            "logs this."
        )
    if bus != "nats":
        return [], warnings, []

    consumes = consumes_events(agent_dir, view)
    try:
        publishes = parse_bool(view.get("event_publishing_enabled", False) or False, "event_publishing_enabled")
    except ValueError:
        publishes = True
    if not (consumes or publishes):
        return [], warnings, []

    issues: list[str] = []
    environment = str(view.get("app_environment", "development"))
    if not str(view.get("nats_url", "") or "").strip() and environment.lower() != "development":
        issues.append(
            f"{named}'event_bus' is 'nats' but 'nats_url' is not set (app_environment is {environment!r}). Outside "
            "development there is no default: localhost is rarely right in a container, and a client pointed at it "
            f"retries forever while the pod looks healthy. Set 'nats_url' in the settings or as "
            f"{settings.override_variable_prefix}NATS_URL."
        )
    heartbeat = view.get("nats_heartbeat_enabled", True)
    if not isinstance(heartbeat, bool):
        issues.append(f"{named}'nats_heartbeat_enabled' must be true or false, got {heartbeat!r}.")
    if not consumes:
        return issues, warnings, []

    if not agent:
        # A namespaced client's queue group is its namespace; only the root reads these keys.
        for key in ("nats_queue_group", "app_name"):
            name = str(view.get(key, "") or "").strip()
            if not name:
                continue
            try:
                validate_subject_segment(name, source=f"The queue group (from '{key}')", subject=f"{name}.dead-letter")
            except ValueError as exc:
                issues.append(str(exc))
            break
        else:
            issues.append(
                "NATS subscriptions require a queue group: set 'nats_queue_group' or 'app_name'. Without one every "
                "replica processes every message."
            )

    durable = str(view.get("nats_durable_name", "") or "").strip()
    if durable and view.get("nats_use_jetstream", False) and not view.get("nats_connection_source"):
        topics = literal_topics(agent_dir)
        subscriptions = view.get("nats_subscriptions", [])
        if topics is not None:
            declared = set(topics) | ({str(topic) for topic in subscriptions if topic} if isinstance(subscriptions, list) else set())
            count = len(declared) + (len(scheduler_modules(agent_dir)) if _mode(view) == SCHEDULER_MODE_EVENT else 0)
            if count > 1:
                issues.append(
                    f"{named}'nats_durable_name' is set to '{durable}' but {count} topics are subscribed. A JetStream "
                    "durable filters one subject, so one name cannot serve them all. Remove the key to derive a "
                    "durable per topic."
                )
    return issues, warnings, []


def process_findings(settings: ProcessSettings) -> Findings:
    """Checks on keys only the process reads: ``event_loop_debug``, read with the runtime's ``parse_bool``."""
    try:
        parse_bool(settings.root_view().get("event_loop_debug", False), "event_loop_debug")
    except ValueError as exc:
        return [f"{exc} Startup fails"], [], []
    return [], [], []


def nats_value_findings(project_dir: Path, view: SettingsView) -> list[str]:
    """Check the NATS delivery keys that would otherwise fail only at startup.

    The same parsers the client uses (``RunLimit.parse``, the readiness modes), so this command and
    startup cannot disagree. ``nats_connection_source`` is checked for its form and for its module
    being found -- without calling the factory: what the source returns depends on the
    deployment's own data and is only known at startup.
    """
    issues: list[str] = []
    for key, minimum in (("nats_max_concurrent_runs", 1), ("nats_extra_runs_per_process", 0)):
        try:
            RunLimit.parse(key, view.get(key), minimum=minimum)
        except ValueError as exc:
            issues.append(str(exc))
    timeout = view.get("nats_handler_timeout")
    if timeout is not None and timeout != "":
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            issues.append(f"'nats_handler_timeout' must be a number of seconds above 0, got {timeout!r}. Unset it for no limit.")
    readiness = view.get("nats_connections_readiness")
    if readiness is not None and str(readiness).strip().lower() not in CONNECTIONS_READINESS_MODES:
        issues.append(f"'nats_connections_readiness' must be one of {', '.join(CONNECTIONS_READINESS_MODES)}, got {readiness!r}.")
    unclaimed = view.get("nats_unclaimed_subjects")
    if unclaimed is not None and str(unclaimed).strip().lower() not in ("fail", "default_connection"):
        issues.append(f"'nats_unclaimed_subjects' must be 'fail' or 'default_connection', got {unclaimed!r}.")
    source = view.get("nats_connection_source")
    if source:
        issue = _connection_source_issue(project_dir, str(source))
        if issue:
            issues.append(issue)
    return issues


def _nats_findings(project_dir: Path, environment: str | None = None) -> list[str]:
    """:func:`nats_value_findings` for a standalone project's own settings."""
    settings = ProcessSettings.load(project_dir, environment)
    if not settings.readable:
        return []
    return nats_value_findings(project_dir, settings.root_view())


def _connection_source_issue(project_dir: Path, path: str) -> str | None:
    """Report a ``nats_connection_source`` that cannot be right, or ``None``.

    Finding the module imports its parent packages, as the import at startup would; the module
    itself is not executed and the factory not called.
    """
    module_path, _, attribute = path.strip().partition(":")
    if not module_path or not attribute:
        return f"'nats_connection_source' is {path!r}; write it as 'package.module:attribute', naming the factory."
    added = str(project_dir) not in sys.path
    if added:
        sys.path.insert(0, str(project_dir))
    try:
        found = importlib.util.find_spec(module_path) is not None
    except (ImportError, ValueError) as exc:
        return f"'nats_connection_source': '{module_path}' cannot be found: {exc}"
    finally:
        if added:
            sys.path.remove(str(project_dir))
    if not found:
        return f"'nats_connection_source': no module '{module_path}' on the project's path; startup would fail."
    return None
