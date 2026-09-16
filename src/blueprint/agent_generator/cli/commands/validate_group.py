"""Validate an image: the agent map, and every agent directory it points at.

``asbs validate`` checks one agent. This checks the thing that contains agents -- a different
question, which is why it is a different mode rather than a heuristic about what the directory
looks like.

What it is really for is making the quiet failures loud. Every defect this module reports was,
at some point, something the process did silently: a settings file in a directory nobody reads
from, an agent whose map entry points at a directory that has since been renamed, process-wide
keys set under an agent where nothing consults them. None of those stop a pod from starting and
passing its probes, which is exactly what makes them expensive to find later.
"""

import sys
import tomllib
from argparse import Namespace
from pathlib import Path
from typing import Any

from blueprint.agents.component.namespace import validate_namespace
from blueprint.agents.config import PROCESS_SCOPE_KEYS
from blueprint.agents.layout import check_agent_layout

AGENT_MAP_FILE = "agents.toml"


def run(args: Namespace) -> None:
    """Execute ``asbs validate --group``.

    Args:
        args: Parsed command-line arguments.
    """
    image_root = Path(args.project_dir).resolve()
    if not image_root.is_dir():
        print(f"Error: Directory does not exist: {image_root}", file=sys.stderr)
        sys.exit(1)

    print(f"Validating Blueprint Agents image: {image_root}")
    print()

    issues, warnings, notices = _findings(image_root)
    _report(issues, warnings, notices)
    sys.exit(1 if issues else 0)


def _findings(image_root: Path) -> tuple[list[str], list[str], list[str]]:
    """Return issues, warnings and notices for the image at ``image_root``."""
    issues: list[str] = []
    warnings: list[str] = []
    notices: list[str] = []

    agent_map = image_root / AGENT_MAP_FILE
    if not agent_map.is_file():
        issues.append(
            f"No {AGENT_MAP_FILE} here, so this directory is not an image. Run 'asbs setup --group' to create one, "
            "or drop --group to validate a single agent."
        )
        return issues, warnings, notices

    try:
        document = tomllib.loads(agent_map.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [f"{AGENT_MAP_FILE} could not be read: {exc}"], warnings, notices

    declared = document.get("agents")
    if not isinstance(declared, dict) or not declared:
        warnings.append(
            f"{AGENT_MAP_FILE} declares no agents. That is what 'asbs setup --group' writes, and an image with no "
            "agents cannot start -- add an entry per agent before deploying it."
        )
        return issues, warnings, notices

    print(f"[ok] {AGENT_MAP_FILE} declares {len(declared)} agent(s): {', '.join(str(name) for name in declared)}")
    print()

    claimed: dict[Path, str] = {}
    for name, entry in declared.items():
        agent_issues, agent_warnings, agent_notices = _agent_findings(image_root, str(name), entry, claimed)
        issues.extend(agent_issues)
        warnings.extend(agent_warnings)
        notices.extend(agent_notices)

    return issues, warnings, notices


def _agent_findings(image_root: Path, name: str, entry: Any, claimed: dict[Path, str]) -> tuple[list[str], list[str], list[str]]:
    """Check one map entry and the directory it points at."""
    issues: list[str] = []
    warnings: list[str] = []
    notices: list[str] = []

    try:
        validate_namespace(name)
    except ValueError as exc:
        issues.append(f"Agent '{name}' in {AGENT_MAP_FILE} cannot be a namespace: {exc}")
        return issues, warnings, notices

    if not isinstance(entry, dict):
        issues.append(f"Agent '{name}' in {AGENT_MAP_FILE} is not a table. Write it as [agents.{name}] with root and module.")
        return issues, warnings, notices

    module = entry.get("module")
    if not module or not isinstance(module, str) or ":" not in module:
        issues.append(f"Agent '{name}' in {AGENT_MAP_FILE} has no usable 'module'. Write it as module = \"package.module:attribute\"")

    declared_root = entry.get("root")
    if not declared_root or not isinstance(declared_root, str):
        issues.append(
            f"Agent '{name}' in {AGENT_MAP_FILE} has no 'root', so there is nowhere to read its settings and prompts "
            'from. Write it as root = "relative/path/to/the/agent".'
        )
        return issues, warnings, notices

    root = (image_root / declared_root).resolve()
    if not root.is_relative_to(image_root):
        issues.append(f"Agent '{name}' has root '{declared_root}', which is outside the image.")
        return issues, warnings, notices
    if not root.is_dir():
        issues.append(
            f"Agent '{name}' has root '{declared_root}', and {root} is not a directory. Either the agent moved and "
            f"{AGENT_MAP_FILE} did not, or the path is a typo."
        )
        return issues, warnings, notices
    if root in claimed:
        issues.append(f"Agents '{claimed[root]}' and '{name}' share the root {declared_root}; they would read each other's files.")
        return issues, warnings, notices
    claimed[root] = name

    for misplaced in check_agent_layout(root, image_root):
        issues.append(misplaced.describe(name))

    if not (root / "src").is_dir():
        warnings.append(f"Agent '{name}' has no 'src' directory at {declared_root}. An agent is the same shape alone or in a group.")

    settings = root / "settings.toml"
    if settings.is_file():
        print(f"[ok] {name}: settings from {declared_root}/settings.toml")
        warnings.extend(_process_key_warnings(name, settings))
    else:
        print(f"[--] {name}: no settings.toml of its own; it reads the image's")

    if root != image_root and root.name != name:
        notices.append(
            f"Agent '{name}' lives in a directory named '{root.name}'. Nothing breaks, but 'asbs dev' in that "
            f"directory serves it as '{root.name}' unless --name says otherwise, so its routes differ between "
            "development and this image."
        )

    return issues, warnings, notices


def _process_key_warnings(name: str, settings: Path) -> list[str]:
    """Report process-wide keys set in an agent's own settings file.

    They are dropped before the merge at runtime rather than obeyed, so this is the difference
    between a key that does nothing and a key somebody believes in.
    """
    try:
        document = tomllib.loads(settings.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [f"Agent '{name}' has a settings.toml that could not be read: {exc}"]

    found: set[str] = set()
    for key, value in document.items():
        if isinstance(value, dict):
            found.update(str(inner).lower() for inner in value if str(inner).lower() in PROCESS_SCOPE_KEYS)
        elif str(key).lower() in PROCESS_SCOPE_KEYS:
            found.add(str(key).lower())

    if not found:
        return []
    return [
        f"Agent '{name}' sets process-wide key(s) in its own settings.toml: {', '.join(sorted(found))}. One process "
        "has one of each, so these are dropped before the merge and the image's settings.toml decides. Move them "
        "there, or remove them."
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
