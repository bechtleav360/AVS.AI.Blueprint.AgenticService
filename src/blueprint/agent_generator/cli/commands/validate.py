"""Validate command - check project structure and configuration."""

import logging
import re
import sys
import tomllib
from argparse import Namespace
from pathlib import Path
from typing import Any

from blueprint.agents.component.namespace import validate_namespace
from blueprint.agents.config import PROCESS_SCOPE_KEYS
from blueprint.agents.io.api.scheduling.scheduler import SCHEDULER_MODE_EVENT, SCHEDULER_MODE_IN_PROCESS, SCHEDULER_MODES

logger = logging.getLogger(__name__)

AGENT_MAP_FILE = "agents.toml"
SETTINGS_FILE = "settings.toml"

IDEMPOTENCY_NOTICE = "\n".join(
    [
        "Event deduplication is off ('idempotency_enabled' is not set), so every handler in",
        "    this project can be run more than once for the same event. Delivery is at-least-once:",
        "    a lost acknowledgement, a pod restart or a rolling deploy each produce a redelivery,",
        "    after the first attempt has already committed its side effects.",
        "    Decide which one this project needs:",
        "      - handlers that are safe to repeat -- nothing to change; or",
        "      - set 'idempotency_enabled = true' and 'idempotency_ttl = <seconds>' in settings.toml,",
        "        with a window that outlasts the broker redelivery window.",
    ]
)


def run(args: Namespace) -> None:
    """Execute the validate command.

    Args:
        args: Parsed command-line arguments
    """
    project_dir = Path(args.project_dir).resolve()

    if not project_dir.is_dir():
        print(f"Error: Project directory does not exist: {project_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Validating Blueprint Agents project: {project_dir}")
    print()

    issues = []
    warnings = []
    notices = []

    # Check for required directories
    required_dirs = ["src", "tests"]
    for dir_name in required_dirs:
        dir_path = project_dir / dir_name
        if not dir_path.is_dir():
            issues.append(f"Missing required directory: {dir_name}/")
        else:
            print(f"✓ Found {dir_name}/")

    # Check for configuration files
    config_files = ["settings.toml", "pyproject.toml"]
    for file_name in config_files:
        file_path = project_dir / file_name
        if not file_path.is_file():
            issues.append(f"Missing configuration file: {file_name}")
        else:
            print(f"✓ Found {file_name}")

    # Check for secrets template
    secrets_example = project_dir / "secrets.toml.example"
    secrets_file = project_dir / "secrets.toml"
    if not secrets_example.is_file():
        warnings.append("Missing secrets.toml.example template")
    else:
        print("✓ Found secrets.toml.example")

    if not secrets_file.is_file():
        warnings.append("Missing secrets.toml (copy from secrets.toml.example)")

    # Check for main.py
    main_file = project_dir / "src" / "main.py"
    if not main_file.is_file():
        issues.append("Missing src/main.py entry point")
    else:
        print("✓ Found src/main.py")

        # Check if main.py uses AppBuilder. Nothing is checked about Config here: main.py is a
        # declaration, and the configuration belongs to whatever builds it -- a main.py that
        # mentions Config at all is the pre-declaration shape, not the expected one.
        content = main_file.read_text()
        if "AppBuilder" not in content:
            warnings.append("src/main.py does not appear to use AppBuilder")

    # Check for component directories
    component_dirs = ["handlers", "services", "api", "models"]
    src_dir = project_dir / "src"
    if src_dir.is_dir():
        for dir_name in component_dirs:
            dir_path = src_dir / dir_name
            if dir_path.is_dir():
                print(f"✓ Found src/{dir_name}/")

    # Check for tests
    tests_dir = project_dir / "tests"
    if tests_dir.is_dir():
        test_files = list(tests_dir.glob("test_*.py"))
        if not test_files:
            warnings.append("No test files found in tests/")
        else:
            print(f"✓ Found {len(test_files)} test file(s)")

    # Check for Docker files
    dockerfile = project_dir / "Dockerfile"
    docker_compose = project_dir / "docker-compose.yml"
    if dockerfile.is_file():
        print("✓ Found Dockerfile")
    else:
        warnings.append("Missing Dockerfile for containerization")

    if docker_compose.is_file():
        print("✓ Found docker-compose.yml")

    # Idempotency decision (spec sec. 7.4): the framework must not choose for the author,
    # so it says nothing at all only when the project has no handlers to run twice.
    notice = _idempotency_notice(project_dir)
    if notice:
        notices.append(notice)

    # Group readiness: what this project must state before it can be hosted beside another
    # agent, and what would otherwise stay silent.
    group_issues, group_warnings, group_notices = _group_findings(project_dir)
    issues.extend(group_issues)
    warnings.extend(group_warnings)
    notices.extend(group_notices)

    # Print summary
    print()
    print("=" * 60)

    if notices:
        print(f"\nNotices ({len(notices)}):")
        for item in notices:
            print(f"  - {item}")

    if not issues and not warnings:
        print("✓ Validation passed! Project structure looks good.")
        sys.exit(0)

    if warnings:
        print(f"\n⚠ Warnings ({len(warnings)}):")
        for warning in warnings:
            print(f"  - {warning}")

    if issues:
        print(f"\n✗ Issues ({len(issues)}):")
        for issue in issues:
            print(f"  - {issue}")
        print("\nProject validation failed. Please fix the issues above.")
        sys.exit(1)
    else:
        print("\n✓ Validation passed with warnings.")
        sys.exit(0)


def _idempotency_notice(project_dir: Path) -> str | None:
    """Return the dedup notice if this project has handlers and has not opted into dedup.

    Returns ``None`` when the project declares ``idempotency_enabled``, whichever way it
    declares it: the author has then made the decision spec sec. 7.4 asks for, and saying
    it again on every run is how a notice stops being read. Also ``None`` when there are no
    handlers, since nothing can be dispatched twice.
    """
    handlers_dir = project_dir / "src" / "handlers"
    if not handlers_dir.is_dir() or not any(handlers_dir.glob("*_handler.py")):
        return None

    settings_file = project_dir / SETTINGS_FILE
    if not settings_file.is_file():
        return IDEMPOTENCY_NOTICE

    settings = _load_settings(settings_file)
    if settings is None:
        return None

    # Dynaconf environments are top-level tables, and the key is valid in any of them.
    if _declares(settings, "idempotency_enabled"):
        return None
    return IDEMPOTENCY_NOTICE


# ----------------------------------------------------------------------------------------------
# Group readiness
#
# Everything below answers one question: can this project be hosted beside another agent in one
# process, and if not, what has it failed to say? There is deliberately no `asbs migrate` --
# main.py is the developer's own declaration, and a tool that rewrites it either guesses at
# intent or fails on anything hand-edited. A checklist plus a validate that names what is
# missing is the honest shape.
# ----------------------------------------------------------------------------------------------

NO_AGENT_MAP_WARNING = "\n".join(
    [
        "No agents.toml, so this project cannot be hosted by 'python -m blueprint.agents.entrypoint'.",
        "    That is not a fault in a project deployed on its own, which is served by its own",
        "    src/main.py as it always was. To make it hostable, three changes and nothing else:",
        "      - src/main.py: 'agent = AppBuilder()...' -- drop the config argument and the",
        "        trailing .build(), so the file declares rather than builds;",
        "      - Dockerfile: the command becomes 'python -m blueprint.agents.entrypoint';",
        "      - agents.toml: one [agents.<name>] entry pointing at 'src.main:agent'.",
        "    The name chosen there becomes the queue group, part of the durable name and the",
        "    /api/<name> prefix, so it is a consumer migration to change after the first deploy.",
    ]
)


def _group_findings(project_dir: Path) -> tuple[list[str], list[str], list[str]]:
    """Report what stops this project being hosted as one agent among several.

    Args:
        project_dir: The project root.

    Returns:
        Issues, warnings and notices, in that order.
    """
    issues: list[str] = []
    warnings: list[str] = []
    notices: list[str] = []

    agent_map_file = project_dir / AGENT_MAP_FILE
    if not agent_map_file.is_file():
        warnings.append(NO_AGENT_MAP_WARNING)
        agents: dict[str, str] = {}
    else:
        agents, map_issues = _read_agent_map(agent_map_file)
        issues.extend(map_issues)
        if agents:
            print(f"[ok] Found {AGENT_MAP_FILE} ({len(agents)} agent(s): {', '.join(agents)})")

    for name, module in agents.items():
        issues.extend(_declaration_issues(project_dir, name, module))
        warnings.extend(_settings_scope_warnings(project_dir, name, module, hosted_alone=len(agents) == 1))

    scheduler_issues, scheduler_notices = _scheduler_findings(project_dir)
    issues.extend(scheduler_issues)
    notices.extend(scheduler_notices)

    return issues, warnings, notices


def _read_agent_map(agent_map_file: Path) -> tuple[dict[str, str], list[str]]:
    """Return ``{agent name: "module:attribute"}`` and whatever is wrong with the file.

    The same shape ``GroupConfig._read_agent_map`` refuses to start on, checked here instead --
    where the answer is a line in a terminal rather than a crash-looping pod. The agent name is
    held to the namespace alphabet by the framework's own validator, because a name repaired
    differently by the queue group, the durable, the cache partition and the telemetry resource
    is four names for one agent.
    """
    try:
        document = tomllib.loads(agent_map_file.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return {}, [f"{AGENT_MAP_FILE} could not be read: {exc}"]

    declared = document.get("agents")
    if not isinstance(declared, dict) or not declared:
        return {}, [f"{AGENT_MAP_FILE} declares no [agents.<name>] entries, so this image contains no agents"]

    agents: dict[str, str] = {}
    issues: list[str] = []
    for name, entry in declared.items():
        module = entry.get("module") if isinstance(entry, dict) else None
        if not module or not isinstance(module, str):
            issues.append(f"Agent '{name}' in {AGENT_MAP_FILE} has no 'module'. Write it as module = \"src.main:agent\"")
            continue
        if ":" not in module:
            issues.append(
                f"Agent '{name}' in {AGENT_MAP_FILE} names the module '{module}', which does not say which attribute "
                'to read. Write it as "package.module:attribute"'
            )
            continue
        try:
            validate_namespace(name)
        except ValueError as exc:
            issues.append(f"Agent '{name}' in {AGENT_MAP_FILE} cannot be a namespace: {exc}")
            continue
        agents[str(name)] = module

    return agents, issues


def _declaration_issues(project_dir: Path, name: str, module: str) -> list[str]:
    """Report an agent whose declaration cannot be found, or is not a declaration.

    Checked against the file rather than by importing it: importing runs the module, which needs
    the project's dependencies installed and is a different failure from the one being looked for.
    What that costs is precision -- this reads text -- and what it buys is a validate that works
    in a checkout.
    """
    module_path, _, attribute = module.partition(":")
    source = _module_file(project_dir, module_path)
    if source is None:
        return [
            f"Agent '{name}' points at '{module_path}', which is not a module in this project. Either the agent map "
            "is out of date, or the declaration moved and the map did not"
        ]

    text = source.read_text(encoding="utf-8")
    if not re.search(rf"^{re.escape(attribute)}\s*=", text, re.MULTILINE):
        return [
            f"Agent '{name}' points at '{module}', but {source.relative_to(project_dir).as_posix()} assigns no "
            f"'{attribute}'. That is the AppBuilder the host builds; without it the process stops before binding "
            "its port"
        ]
    return []


def _settings_scope_warnings(project_dir: Path, name: str, module: str, *, hosted_alone: bool) -> list[str]:
    """Report settings that will not survive this agent being hosted beside another.

    Two things go wrong, and neither raises. An agent's own settings file is read from the
    directory its declaration lives in, so one written anywhere else is merged into no scope at
    all; and a key that describes the *process* -- the port it binds, the bus it speaks, the
    environment it loads -- is dropped with a warning when it arrives under one agent's scope,
    because one process has exactly one of each.

    A project hosted alone is the process, so its settings.toml is the process's own file and
    neither applies: it is reported only once there is a second agent to share with. The same
    exemption covers an agent declared at the project root in a group -- ``main:agent`` rather
    than ``src.main:agent`` -- whose settings file *is* the process's, which the merge recognises
    and leaves at the root rather than scoping.
    """
    if hosted_alone:
        return []

    module_path = module.partition(":")[0]
    source = _module_file(project_dir, module_path)
    if source is None:
        return []

    fragment = source.parent / SETTINGS_FILE
    if fragment == project_dir / SETTINGS_FILE:
        return []

    if not fragment.is_file():
        return [
            f"Agent '{name}' ships no settings of its own: its declaration is in "
            f"{source.parent.relative_to(project_dir).as_posix()}/ and an agent's settings.toml is read from there. "
            "Every key it reads will come from the group's own settings file, where it is shared with the other agents"
        ]

    settings = _load_settings(fragment)
    if settings is None:
        return []

    scoped = sorted(key for key in PROCESS_SCOPE_KEYS if _declares(settings, key))
    if not scoped:
        return []
    return [
        f"Agent '{name}' declares the process-scope key(s) {', '.join(scoped)} in "
        f"{fragment.relative_to(project_dir).as_posix()}. One process binds one port, speaks one event bus and loads "
        "one environment, so these are dropped with a warning when this agent's settings are merged under its own "
        "scope. Move them to the group's settings file"
    ]


def _scheduler_findings(project_dir: Path) -> tuple[list[str], list[str]]:
    """Report a scheduler that has not said how it is fired, or that nothing fires.

    ``scheduler_mode`` has no default and fails at ``build()`` when a scheduler is registered
    without it, so that half is only reported earlier here. The half that fails *nowhere* is the
    reason this check exists: ``"event"`` mode starts no timer and waits for a tick that an
    external ``CronJob`` must publish, and nothing in this repository generates one -- so a
    project can be correct in every mechanical respect and simply never run.
    """
    schedulers = _scheduler_modules(project_dir)
    if not schedulers:
        return [], []

    settings = _load_settings(project_dir / SETTINGS_FILE)
    mode = _value_of(settings, "scheduler_mode") if settings is not None else None

    if mode is None:
        return [
            f"{len(schedulers)} scheduler(s) under src/schedulers/ and no 'scheduler_mode' in {SETTINGS_FILE}. It has "
            f"no default, because neither value is safe to inherit, so build() fails: set '{SCHEDULER_MODE_IN_PROCESS}' "
            f"to run a timer in the process (needs .with_cache(), or every replica runs every tick) or "
            f"'{SCHEDULER_MODE_EVENT}' to take the tick as an event (needs 'event_bus', and something publishing it)"
        ], []

    if mode not in SCHEDULER_MODES:
        return [f"'scheduler_mode' is {mode!r} in {SETTINGS_FILE}; it must be one of {', '.join(SCHEDULER_MODES)}"], []

    issues: list[str] = []
    notices: list[str] = []
    if mode == SCHEDULER_MODE_EVENT:
        # A notice, not an issue: nothing here can tell whether a CronJob exists, and the thing
        # that would know -- the deployment -- is outside this project. The framework cannot
        # report it either, which is exactly why it is said here.
        notices.append(
            "\n".join(
                [
                    f"'scheduler_mode' is '{SCHEDULER_MODE_EVENT}', so no timer runs in this process: each tick",
                    "    arrives as an event on '<agent>.scheduler.<scheduler name>', published by an external",
                    "    CronJob. Nothing in this project generates that CronJob, and a scheduler waiting for a",
                    "    tick nobody publishes reports itself healthy and never runs. Confirm one exists, on the",
                    "    schedule the scheduler declares, for every scheduler under src/schedulers/.",
                ]
            )
        )
        if not _declares(settings or {}, "event_bus"):
            # This one *does* fail at startup -- the tick is an ordinary event, so without a
            # transport there is nothing to subscribe to -- so it is an issue rather than advice.
            issues.append(
                f"'scheduler_mode' is '{SCHEDULER_MODE_EVENT}' and no 'event_bus' is set. The tick arrives as an event, "
                "so there is nothing to subscribe to and wiring the scheduler fails at startup"
            )
    elif not _main_declares_a_cache(project_dir):
        notices.append(
            "\n".join(
                [
                    f"'scheduler_mode' is '{SCHEDULER_MODE_IN_PROCESS}' and src/main.py declares no cache. Each tick is",
                    "    claimed in the agent's own cache so that one replica runs it; with no cache to claim in,",
                    "    every replica runs every tick. Add .with_cache() unless this runs as a single replica.",
                ]
            )
        )
    return issues, notices


def _scheduler_modules(project_dir: Path) -> list[Path]:
    """Return the scheduler modules this project defines."""
    schedulers_dir = project_dir / "src" / "schedulers"
    if not schedulers_dir.is_dir():
        return []
    return [path for path in sorted(schedulers_dir.glob("*.py")) if path.name != "__init__.py"]


def _main_declares_a_cache(project_dir: Path) -> bool:
    """Report whether the declaration registers a cache for the tick claim to use."""
    main_file = project_dir / "src" / "main.py"
    return main_file.is_file() and ".with_cache(" in main_file.read_text(encoding="utf-8")


def _module_file(project_dir: Path, module_path: str) -> Path | None:
    """Resolve a dotted module path to the file that defines it, or ``None``."""
    relative = Path(*module_path.split("."))
    for candidate in (project_dir / relative.with_suffix(".py"), project_dir / relative / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _load_settings(settings_file: Path) -> dict[str, Any] | None:
    """Parse a settings file, or ``None`` when there is nothing readable to parse.

    A file that cannot be read is reported by its own check; guessing at a key from an
    unparseable file would be worse than staying quiet.
    """
    if not settings_file.is_file():
        return None
    try:
        with settings_file.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.debug("Could not read %s: %s", settings_file, exc)
        return None


def _declares(settings: dict[str, Any], key: str) -> bool:
    """Report whether ``key`` appears at the top level or in any Dynaconf environment."""
    if key in settings:
        return True
    return any(isinstance(value, dict) and key in value for value in settings.values())


def _value_of(settings: dict[str, Any], key: str) -> Any | None:
    """Return ``key``'s value from the top level, or from the first environment that sets it.

    Which environment is in force is a runtime decision this command cannot make, so a key set
    in any of them counts as set. That is the right answer for the checks here, which ask whether
    the author has *decided* something, not what today's value is.
    """
    if key in settings:
        return settings[key]
    for value in settings.values():
        if isinstance(value, dict) and key in value:
            return value[key]
    return None
