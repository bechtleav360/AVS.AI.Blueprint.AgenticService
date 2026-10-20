"""Validate an image: the agent map, the group file, and every agent directory the map points at.

``asbs validate`` checks one agent. This checks the thing that contains agents -- a different
question, which is why it is a different mode rather than a heuristic about what the directory
looks like.

What it is really for is making the quiet failures loud. Every defect this module reports was,
at some point, something the process did silently: a settings file in a directory nobody reads
from, an agent whose map entry points at a directory that has since been renamed, process-wide
keys set under an agent where nothing consults them. None of those stop a pod from starting and
passing its probes, which is exactly what makes them expensive to find later.

Where the runtime has the rule as a public function, this runs that function: the group file is
resolved by ``GroupConfig.resolve_at`` against a stub environment, an agent's settings are layered
by ``layer_settings_document``, crontabs go through ``validate_crontab``.
"""

import ast
import importlib.util
import logging
import os
import re
import sys
import tomllib
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from blueprint.agents import group_config as group_config_module
from blueprint.agents.component.namespace import validate_namespace
from blueprint.agents.config.config import AGENT_REFUSED_KEYS
from blueprint.agents.group_config import (
    AGENTS_ENV,
    CRITICAL_AGENTS_ENV,
    GROUP_CONFIG_ENV,
    GROUP_ENV,
    GroupConfig,
    GroupConfigError,
    group_file_path,
)
from blueprint.agents.io.api.eventing.dapr import shared_topic_warnings
from blueprint.agents.layout import check_agent_layout

from ..utils.cancellation_check import swallowed_cancellation_warning, swallowed_cancellations
from .validate import (
    SECRETS_FILE,
    SETTINGS_FILE,
    Findings,
    ProcessSettings,
    SettingsView,
    dedup_findings,
    literal_topics,
    nats_value_findings,
    process_findings,
    scheduler_findings,
    transport_findings,
)

AGENT_MAP_FILE = "agents.toml"
AGENT_MAP_ENV = "BLUEPRINT_AGENT_MAP"

# How many absolute `src` imports one warning lists before it summarises the rest.
_IMPORTS_SHOWN = 5


@dataclass(frozen=True)
class _CheckedAgent:
    """An agent whose entry resolved, with what it reads -- for the checks that span agents."""

    name: str
    root: Path
    view: SettingsView


def run(args: Namespace) -> None:
    """Execute ``asbs validate --group``.

    Args:
        args: Parsed command-line arguments.
    """
    image_root = Path(args.project_dir).resolve()
    if not image_root.is_dir():
        print(f"Error: Directory does not exist: {image_root}", file=sys.stderr)
        sys.exit(1)

    agent_map = _agent_map_path(image_root, getattr(args, "agent_map", None))

    print(f"Validating Blueprint Agents image: {image_root}")
    if agent_map.parent != image_root:
        print(f"Agent map: {agent_map}")
    environment = getattr(args, "environment", None)
    print(f"Environment: {ProcessSettings.load(image_root, environment).environment} (choose another with --environment)")
    print()

    issues, warnings, notices = image_findings(
        image_root,
        agent_map,
        environment=environment,
        group_config=getattr(args, "group_config", None),
        group_name=getattr(args, "group_name", None),
    )
    _report(issues, warnings, notices)
    sys.exit(1 if issues else 0)


def _agent_map_path(image_root: Path, configured: str | None) -> Path:
    """Return where the agent map is, which is not necessarily inside the directory being checked.

    The runtime resolves every agent ``root`` against the image root -- the directory the process
    runs in -- while the map itself may sit anywhere, because ``BLUEPRINT_AGENT_MAP`` relocates it.

    Args:
        image_root: The directory being validated, which agent roots resolve against.
        configured: ``--agent-map``, if it was given.

    Returns:
        The map's path, absolute. Relative values resolve against the image root, the same way
        ``BLUEPRINT_AGENT_MAP`` does at runtime.
    """
    declared = (configured or os.environ.get(AGENT_MAP_ENV, "") or "").strip()
    if not declared:
        return image_root / AGENT_MAP_FILE
    path = Path(declared)
    return path if path.is_absolute() else image_root / path


def image_findings(
    image_root: Path,
    agent_map: Path,
    *,
    environment: str | None = None,
    group_config: str | None = None,
    group_name: str | None = None,
) -> Findings:
    """Return issues, warnings and notices for the image at ``image_root``.

    Args:
        image_root: The directory agent roots resolve against, as at runtime.
        agent_map: The map to read, which may be outside ``image_root``.
        environment: The environment to check; see ``ProcessSettings.load``.
        group_config: ``--group-config``: the group file, if not ``BLUEPRINT_GROUP_CONFIG`` or the default.
        group_name: ``--group-name``: check only this group of the group file.
    """
    issues: list[str] = []
    warnings: list[str] = []
    notices: list[str] = []

    settings = ProcessSettings.load(image_root, environment)

    if not agent_map.is_file():
        issues.append(
            f"No agent map at {agent_map}, so this directory is not an image. Run 'asbs setup --group' to create "
            f"one, point at an existing one with --agent-map (or {AGENT_MAP_ENV}), or drop --group to validate a "
            "single agent."
        )
        return issues, warnings, notices

    try:
        document = tomllib.loads(agent_map.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [f"{AGENT_MAP_FILE} could not be read: {exc}"], warnings, notices

    declared = document.get("agents")
    if not isinstance(declared, dict) or not declared:
        issues.append(
            f"Agent map {agent_map} declares no [agents.<name>] entries, so this image contains no agents and the "
            "process refuses to start. 'asbs setup --group' writes it empty: add an entry per agent before deploying."
        )
        return issues, warnings, notices

    print(f"[ok] {AGENT_MAP_FILE} declares {len(declared)} agent(s): {', '.join(str(name) for name in declared)}")
    print()

    issues.extend(settings.problems)
    warnings.extend(settings.unread_key_warnings())

    claimed: dict[Path, str] = {}
    checked: list[_CheckedAgent] = []
    map_valid = True
    for name, entry in declared.items():
        agent_issues, agent_warnings, agent_notices, agent = _agent_findings(image_root, str(name), entry, claimed, settings)
        issues.extend(agent_issues)
        warnings.extend(agent_warnings)
        notices.extend(agent_notices)
        if agent is None:
            map_valid = False
        else:
            checked.append(agent)

    if settings.readable:
        root_issues = nats_value_findings(image_root, settings.root_view())
        issues.extend(root_issues)
        for agent in checked:
            issues.extend(
                f"Agent '{agent.name}': {issue}" for issue in nats_value_findings(agent.root, agent.view) if issue not in root_issues
            )
        found = process_findings(settings)
        issues.extend(found[0])
        warnings.extend(_shared_topic_warnings(settings, checked))

    # The runtime reads the map before the group, and stops at its first defect; those are all
    # reported above, so the group is resolved only once the map is one the runtime accepts.
    if map_valid:
        group_issues, group_warnings, group_notices = group_findings(
            image_root, agent_map, group_config=group_config, group_name=group_name
        )
        issues.extend(group_issues)
        warnings.extend(group_warnings)
        notices.extend(group_notices)

    return issues, warnings, notices


def _agent_findings(
    image_root: Path, name: str, entry: Any, claimed: dict[Path, str], settings: ProcessSettings
) -> tuple[list[str], list[str], list[str], _CheckedAgent | None]:
    """Check one map entry and the directory it points at.

    Returns:
        Issues, warnings, notices, and the agent when its entry resolves (``None`` when the
        runtime's map reading would refuse it).
    """
    issues: list[str] = []
    warnings: list[str] = []
    notices: list[str] = []

    try:
        validate_namespace(name)
    except ValueError as exc:
        issues.append(f"Agent '{name}' in {AGENT_MAP_FILE} cannot be a namespace: {exc}")
        return issues, warnings, notices, None

    if not isinstance(entry, dict):
        issues.append(f"Agent '{name}' in {AGENT_MAP_FILE} is not a table. Write it as [agents.{name}] with root and module.")
        return issues, warnings, notices, None

    module = entry.get("module")
    module_ok = bool(module) and isinstance(module, str) and ":" in module
    if not module_ok:
        issues.append(f"Agent '{name}' in {AGENT_MAP_FILE} has no usable 'module'. Write it as module = \"package.module:attribute\"")

    declared_root = entry.get("root")
    if not declared_root or not isinstance(declared_root, str):
        issues.append(
            f"Agent '{name}' in {AGENT_MAP_FILE} has no 'root', so there is nowhere to read its settings and prompts "
            'from. Write it as root = "relative/path/to/the/agent", relative to the image root.'
        )
        return issues, warnings, notices, None

    root = (image_root / declared_root).resolve()
    if not root.is_relative_to(image_root):
        issues.append(f"Agent '{name}' has root '{declared_root}', which is outside the image.")
        return issues, warnings, notices, None
    if not root.is_dir():
        issues.append(
            f"Agent '{name}' has root '{declared_root}', and {root} is not a directory. Either the agent moved and "
            f"{AGENT_MAP_FILE} did not, or the path is a typo."
        )
        return issues, warnings, notices, None
    if root in claimed:
        issues.append(f"Agents '{claimed[root]}' and '{name}' share the root {declared_root}; they would read each other's files.")
        return issues, warnings, notices, None
    claimed[root] = name

    if module_ok:
        issues.extend(_declaration_issues(image_root, name, str(module)))

    for misplaced in check_agent_layout(root):
        issues.append(misplaced.describe(name))

    if not (root / "src").is_dir():
        warnings.append(f"Agent '{name}' has no 'src' directory at {declared_root}. An agent is the same shape alone or in a group.")
    elif (root / "src").resolve() != (image_root / "src").resolve():
        warnings.extend(_absolute_src_import_warnings(name, root))
    if (root / "src").is_dir():
        swallowed = swallowed_cancellations(root / "src")
        if swallowed:
            warnings.append(swallowed_cancellation_warning(name, swallowed))

    # The agent's own files, as AgentGroup.from_config collects them: beside its root's src. An
    # agent whose root is the image root has no files of its own -- its settings are the process's.
    fragments: list[dict[str, Any]] = []
    if root != image_root:
        settings_file = root / SETTINGS_FILE
        if settings_file.is_file():
            print(f"[ok] {name}: settings from {declared_root}/{SETTINGS_FILE}")
        else:
            print(f"[--] {name}: no {SETTINGS_FILE} of its own; it reads the image's")
        for path in (root / SECRETS_FILE, settings_file):
            if not path.is_file():
                continue
            try:
                document = tomllib.loads(path.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError) as exc:
                issues.append(f"Agent '{name}' has a {path.name} that could not be read, and the merge refuses it at startup: {exc}")
                continue
            secret = path.name == SECRETS_FILE
            issues.extend(_self_scoped_issues(name, path.name, document))
            warnings.extend(_process_key_warnings(name, path.name, document, secret=secret))
            fragments.append(document)
        issues.extend(_root_key_issues(name, settings, fragments))

    view = settings.agent_view(name, fragments)
    if settings.readable:
        where = f"{declared_root}/{SETTINGS_FILE} or the image's {SETTINGS_FILE}"
        for found in (
            scheduler_findings(root, view=view, settings=settings, where=where, agent=name),
            dedup_findings(root, view=view, settings=settings, agent=name),
            transport_findings(root, view=view, settings=settings, agent=name),
        ):
            issues.extend(found[0])
            warnings.extend(found[1])
            notices.extend(found[2])

    if root != image_root and root.name != name:
        notices.append(
            f"Agent '{name}' lives in a directory named '{root.name}'. Nothing breaks; to develop it with the "
            f"routes this image gives it, run 'asbs dev --name {name}' in that directory -- without --name it is "
            "served on its own, at the root namespace."
        )

    return issues, warnings, notices, _CheckedAgent(name, root, view)


def _declaration_issues(image_root: Path, name: str, module: str) -> list[str]:
    """Report an agent whose declaration cannot be found, or is not assigned where the map says.

    Checked against the file rather than by importing it. A module that is not a file of the
    image is fine when its top-level package is installed elsewhere -- an agent installed as a
    distribution imports from site-packages while its files sit in the image -- and that is
    looked up without importing anything.
    """
    module_path, _, attribute = module.partition(":")
    source = _module_file(image_root, module_path)
    if source is None:
        if _installed_elsewhere(image_root, module_path):
            return []
        return [
            f"Agent '{name}' points at '{module_path}', which is not a module in this image (looked for it under "
            f"{image_root}). Either the agent map is out of date, or the declaration moved and the map did not; a "
            "critical agent then stops the process"
        ]
    text = source.read_text(encoding="utf-8")
    if not re.search(rf"^{re.escape(attribute)}\s*[:=]", text, re.MULTILINE):
        return [
            f"Agent '{name}' points at '{module}', but {source.relative_to(image_root).as_posix()} assigns no "
            f"'{attribute}'. That is the AppBuilder the host builds; without it the process stops before binding "
            "its port"
        ]
    return []


def _module_file(image_root: Path, module_path: str) -> Path | None:
    """Resolve a dotted module path to the file in the image that defines it, or ``None``."""
    relative = Path(*module_path.split("."))
    for candidate in (image_root / relative.with_suffix(".py"), image_root / relative / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _installed_elsewhere(image_root: Path, module_path: str) -> bool:
    """Whether the module's top-level package is importable from outside the image (found, never imported)."""
    top = module_path.split(".")[0]
    try:
        spec = importlib.util.find_spec(top)
    except (ImportError, ValueError):
        return False
    if spec is None:
        return False
    locations = list(spec.submodule_search_locations or []) or ([spec.origin] if spec.origin else [])
    return bool(locations) and not any(Path(location).resolve().is_relative_to(image_root) for location in locations)


def _self_scoped_issues(name: str, file_name: str, document: dict[str, Any]) -> list[str]:
    """Report an agent file that scopes keys under the agent's own name.

    The file becomes that agent's scope when merged, so a ``[default.<agent>]`` section in it
    nests to ``<agent>.<agent>.*`` and nothing reads those keys. The runtime refuses it for the
    environment in force; this reports it in any section, because a section that is inactive here
    is active in another deployment.
    """
    found = [
        f"[{section}.{key}]"
        for section, value in document.items()
        if isinstance(value, dict)
        for key in value
        if str(key).lower() == name.lower()
    ]
    found += [f"[{key}]" for key, value in document.items() if isinstance(value, dict) and str(key).lower() == name.lower()]
    if not found:
        return []
    return [
        f"Agent '{name}' scopes its own settings under its own name ({', '.join(sorted(set(found)))}) in its "
        f"{file_name}. That file becomes the agent's scope when it is merged, so those keys nest as "
        f"'{name}.{name}.*' and nothing reads them; the runtime refuses it at startup. Write them at the top level or "
        "under a plain [default] -- which also works standalone, because a scoped lookup falls back to the root key."
    ]


def _process_key_warnings(name: str, file_name: str, document: dict[str, Any], *, secret: bool) -> list[str]:
    """Report the keys the merge drops from an agent's file: process-wide and deployment-identity keys.

    Reported in any section, which is stricter than the merge (it drops them from the sections
    in force), because a section inactive here is active in another deployment. Keys only -- a
    secrets file's values are never shown.
    """
    found: set[str] = set()
    for key, value in document.items():
        if isinstance(value, dict):
            found.update(str(inner).lower() for inner in value if str(inner).lower() in AGENT_REFUSED_KEYS)
        elif str(key).lower() in AGENT_REFUSED_KEYS:
            found.add(str(key).lower())
    if not found:
        return []
    kind = "secrets file" if secret else "settings"
    return [
        f"Agent '{name}' sets process-wide key(s) in its own {file_name}: {', '.join(sorted(found))}. One process "
        f"has one of each, so these are dropped from the agent's {kind} before the merge, with a warning, and the "
        f"image's {SETTINGS_FILE} decides. Move them there, or remove them."
    ]


def _root_key_issues(name: str, settings: ProcessSettings, fragments: list[dict[str, Any]]) -> list[str]:
    """Report an image key named like the agent that is not a table, which the merge refuses (S12)."""
    contributes = any(key for document in fragments for key in settings.layered(document) if str(key).lower() not in AGENT_REFUSED_KEYS)
    existing = settings.tree.get(name.lower())
    if not contributes or existing is None or isinstance(existing, dict):
        return []
    return [
        f"Agent '{name}' cannot have settings of its own: the image's configuration already uses '{name}' as a key, "
        "with a value that is not a section. Merging the agent's file would replace that value for the whole process, "
        "so startup fails. Rename the agent or the key."
    ]


def _shared_topic_warnings(settings: ProcessSettings, checked: list[_CheckedAgent]) -> list[str]:
    """Warn about a Dapr topic two agents declare while one of them does not deduplicate (S5).

    What ``DaprEventing`` warns about at startup: there is one delivery for both agents, and so
    one answer -- a retry asked for by one redelivers the event to every agent of the topic. Read
    from literal ``get_subscribed_topics`` returns only.
    """
    if str(settings.root_view().get("event_bus", "") or "").strip().lower() != "dapr":
        return []
    views = {agent.name: agent.view for agent in checked}
    topics = {agent.name: literal_topics(agent.root) or [] for agent in checked}
    return shared_topic_warnings(topics, lambda name: views[name].get("idempotency_enabled", False))


class _Collected(logging.Handler):
    """Keeps the WARNING and ERROR records group resolution logs, to report them as warnings."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def group_findings(image_root: Path, agent_map: Path, *, group_config: str | None = None, group_name: str | None = None) -> Findings:
    """Resolve the group file the way the process does, and report what it refuses.

    The runtime's ``GroupConfig.resolve_at`` runs against a stub environment holding the group
    file, the agent map, and whichever of ``BLUEPRINT_GROUP``, ``BLUEPRINT_AGENTS`` and
    ``BLUEPRINT_CRITICAL_AGENTS`` this environment sets, so its refusals are reported in its own
    words. Without a name, every group of a multi-group file is resolved in turn. With no group
    file and nothing in the environment there is nothing to resolve: which agents a process runs
    is the deployment's decision, made at container start.

    Args:
        image_root: The image root.
        agent_map: The agent map, already checked.
        group_config: ``--group-config``; else ``BLUEPRINT_GROUP_CONFIG``; else ``./deployment-groups.yaml``.
        group_name: ``--group-name``, which wins over ``BLUEPRINT_GROUP``.
    """
    configured = (group_config or os.environ.get(GROUP_CONFIG_ENV, "") or "").strip()
    group_file = group_file_path({GROUP_CONFIG_ENV: configured}, image_root)

    environ = {AGENT_MAP_ENV: str(agent_map), GROUP_CONFIG_ENV: str(group_file)}
    for variable in (GROUP_ENV, AGENTS_ENV, CRITICAL_AGENTS_ENV):
        value = os.environ.get(variable, "").strip()
        if value:
            environ[variable] = value
    if group_name:
        environ[GROUP_ENV] = group_name

    named = GROUP_ENV in environ or AGENTS_ENV in environ
    if not named and not group_file.is_file():
        return (
            [],
            [],
            [
                f"No group file at {group_file}, and neither {GROUP_ENV} nor {AGENTS_ENV} is set, so no group was "
                "resolved: which agents a process runs is the deployment's decision. Pass --group-config (or set "
                f"{GROUP_CONFIG_ENV}) to check the group file a deployment mounts."
            ],
        )

    candidates = [environ]
    if not named:
        names = _group_names(group_file)
        if len(names) > 1:
            candidates = [{**environ, GROUP_ENV: name} for name in names]

    issues: list[str] = []
    warnings: list[str] = []
    resolver_logger = logging.getLogger(group_config_module.__name__)
    for environment in candidates:
        collected = _Collected()
        resolver_logger.addHandler(collected)
        try:
            group = GroupConfig.resolve_at(image_root, environ=environment)
        except GroupConfigError as exc:
            if str(exc) not in issues:
                issues.append(str(exc))
            continue
        finally:
            resolver_logger.removeHandler(collected)
        print(f"[ok] group '{group.name}' resolves to: {', '.join(group.agent_names) or 'no agents'}")
        warnings.extend(message for message in collected.messages if message not in warnings)
    return issues, warnings, []


def _group_names(group_file: Path) -> list[str]:
    """The group names a group file declares, in order and without repeats; empty when it cannot be read.

    Only to know which groups to resolve: everything wrong with the file is the runtime's to say.
    """
    try:
        document = yaml.safe_load(group_file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return []
    groups = document.get("groups") if isinstance(document, dict) else None
    if not isinstance(groups, list):
        return []
    names: dict[str, None] = {}
    for entry in groups:
        if isinstance(entry, dict) and str(entry.get("name", "") or "").strip():
            names[str(entry["name"]).strip()] = None
    return list(names)


def _absolute_src_import_warnings(name: str, root: Path) -> list[str]:
    """Report an agent that imports its own code as the top-level package ``src``.

    Standalone that works, because the agent's directory is the working directory. In a group the
    agent is imported by its ``module`` path and nothing puts its directory on ``sys.path``, so
    ``src`` resolves to nothing -- or to the image root's own ``src``, a different package. A
    non-critical agent is then skipped at startup with one ERROR line and its routes are missing,
    which is why this is reported here rather than left to the log.

    A warning, not an issue: a critical agent fails loudly by itself, and a non-critical one does
    not stop the image starting. Parsed rather than grepped or imported.
    """
    found: list[str] = []
    for path in sorted((root / "src").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue  # not this check's to report: the runtime's import names it precisely
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            if any(imported == "src" or imported.startswith("src.") for imported in names):
                found.append(f"{path.relative_to(root).as_posix()}:{node.lineno}")

    if not found:
        return []
    shown = ", ".join(found[:_IMPORTS_SHOWN])
    more = f" and {len(found) - _IMPORTS_SHOWN} more" if len(found) > _IMPORTS_SHOWN else ""
    return [
        f"Agent '{name}' imports its own code as 'src' ({shown}{more}). That works standalone and fails in a group, "
        "where the agent is imported by its module path and 'src' is not its package: a non-critical agent is then "
        "skipped at startup and its routes are missing. Make these imports relative -- 'from .x import Y' in "
        "src/main.py, 'from ..x import Y' one package down -- which keeps working standalone."
    ]


def _report(issues: list[str], warnings: list[str], notices: list[str]) -> None:
    """Print the three grades, worst first."""
    for label, entries in (("Issues", issues), ("Warnings", warnings), ("Notices", notices)):
        if not entries:
            continue
        print()
        print(f"{label}:")
        for entry in entries:
            print(f"  - {entry}")

    print()
    if issues:
        print(f"Not valid: {len(issues)} issue(s) would stop this image starting.")
    elif warnings:
        print(f"Valid, with {len(warnings)} warning(s).")
    else:
        print("Valid.")
