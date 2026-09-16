"""Dev command - start development server."""

import ast
import atexit
import logging
import os
import re
import tempfile
import subprocess
import sys
import tomllib
from argparse import Namespace
from pathlib import Path

from blueprint.agents.component.namespace import validate_namespace

logger = logging.getLogger(__name__)

AGENT_MAP_FILE = "agents.toml"
DECLARATION_ENTRY_POINT = "src/main.py"
LEGACY_ENTRY_POINT = "src/main.py"
AGENT_MAP_ENV = "BLUEPRINT_AGENT_MAP"

GROUP_FACTORY = "blueprint.agents.entrypoint:create_group_app"
LEGACY_APP = "src.main:app"
STANDALONE_FACTORY = "src.main:create_app"

AGENTS_ENV = "BLUEPRINT_AGENTS"
GROUP_ENV = "BLUEPRINT_GROUP"


def run(args: Namespace) -> None:
    """Execute the dev command.

    Runs the project the way the deployment does, under the agents' **real** namespaces. A
    development server at the root namespace would serve ``/api/orders/{id}`` where production
    serves ``/api/order/orders/{id}`` and would consume under a different queue group, so every
    local URL and every local integration test would differ from the deployed one in a way
    nothing reports.

    Args:
        args: Parsed command-line arguments
    """
    agent_map = Path(AGENT_MAP_FILE)
    entry = Path(DECLARATION_ENTRY_POINT)
    requested_name = (getattr(args, "name", "") or "").strip()

    if requested_name and entry.is_file():
        # Explicitly asked for the grouped shape: serve the agent under the namespace it will
        # have in an image, so the routes match production. The map is written outside the
        # project -- an agents.toml left in an agent directory is the one file it must not have.
        command = _group_command(args, _temporary_agent_map(args))
    elif agent_map.is_file():
        command = _group_command(args, agent_map)
    elif _declares(entry, "create_app"):
        # A standalone agent, served through its own factory. Nothing group-related is
        # involved: no map, no group, no namespace -- a group of one is still a group, and an
        # agent must not have to declare itself one to run alone.
        print("Serving this agent on its own (src.main:create_app), at the root namespace.")
        print("Use --name <agent> to serve it under the namespace a group image would give it.")
        command = _uvicorn_command(args, STANDALONE_FACTORY, factory=True)
    elif entry.is_file() and _declares(entry, "app"):
        # A project from before the declaration split, which builds its own application. It is
        # served the way it always was, and goes on working.
        print(f"No {AGENT_MAP_FILE} and no create_app(); serving {LEGACY_APP} at the root namespace.")
        command = _legacy_command(args)
    else:
        print(f"Error: no {AGENT_MAP_FILE}, and {DECLARATION_ENTRY_POINT} defines neither create_app nor app", file=sys.stderr)
        print("Make sure you are in a Blueprint Agents project directory", file=sys.stderr)
        sys.exit(1)

    print(f"Starting development server on {args.host}:{args.port}")
    print("Press Ctrl+C to stop")
    print()

    try:
        subprocess.run(command, check=True)
    except FileNotFoundError:
        print("Error: uvicorn not found", file=sys.stderr)
        print("Install with: pip install uvicorn", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error: Server exited with code {e.returncode}", file=sys.stderr)
        sys.exit(e.returncode)
    except KeyboardInterrupt:
        print("\nServer stopped")
        sys.exit(0)


def _group_command(args: Namespace, agent_map: Path) -> list[str]:
    """Return the uvicorn command that serves this project's agents as a group.

    Sets ``BLUEPRINT_AGENTS`` in this process's environment so the child inherits it, but only
    when the environment names no group of its own: a developer who has exported
    ``BLUEPRINT_GROUP`` or ``BLUEPRINT_AGENTS`` is reproducing a particular deployment, and
    overriding that from a default read out of the agent map would quietly serve something else.
    """
    if not _group_already_chosen():
        agents = _requested_agents(args) or _agents_in_map(agent_map)
        os.environ[AGENTS_ENV] = ",".join(agents)
        print(f"Hosting {len(agents)} agent(s): {', '.join(agents)}")
    else:
        print(f"Group taken from the environment ({GROUP_ENV}/{AGENTS_ENV}); the agent map is not consulted for it.")

    return _uvicorn_command(args, GROUP_FACTORY, factory=True)


def _legacy_command(args: Namespace) -> list[str]:
    """Return the uvicorn command for a project that still builds its own application."""
    return _uvicorn_command(args, LEGACY_APP, factory=False)


def _uvicorn_command(args: Namespace, target: str, *, factory: bool) -> list[str]:
    """Assemble the uvicorn invocation.

    Uses ``sys.executable`` (the interpreter that launched ``asbs``) rather than a literal
    "python": on Windows with uv-managed venvs the latter can resolve to the base interpreter,
    which can't see the venv's site-packages (#15).
    """
    command = [sys.executable, "-m", "uvicorn", target]
    if factory:
        command.append("--factory")
    command.extend(["--reload", "--host", args.host, "--port", str(args.port)])
    return command


def _group_already_chosen() -> bool:
    """Report whether the environment already says which agents this process runs."""
    return any(os.environ.get(name, "").strip() for name in (GROUP_ENV, AGENTS_ENV))


def _requested_agents(args: Namespace) -> list[str]:
    """Return the agents named on the command line, if any."""
    requested = getattr(args, "agents", None) or ""
    return [name.strip() for name in requested.split(",") if name.strip()]


def _agents_in_map(agent_map: Path) -> list[str]:
    """Return every agent the image contains, which is the default group for development.

    Every agent rather than a guess at one: the map is the complete list of what this project
    holds, and a developer who wants a subset says so with ``--agents``. Choosing one of several
    here would be the tool deciding which agent is the interesting one.

    Raises:
        SystemExit: if the map cannot be read or declares no agents. Either way there is nothing
            to serve, and the failure names the file rather than surfacing from inside the
            framework's group resolution.
    """
    try:
        document = tomllib.loads(agent_map.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(f"Error: {agent_map} could not be read: {exc}", file=sys.stderr)
        sys.exit(1)

    agents = document.get("agents")
    if not isinstance(agents, dict) or not agents:
        print(f"Error: {agent_map} declares no [agents.<name>] entries, so there is nothing to serve", file=sys.stderr)
        sys.exit(1)
    return [str(name) for name in agents]


def _declares(entry_point: Path, name: str) -> bool:
    """Report whether ``entry_point`` defines ``name`` at module level.

    Read rather than imported: importing it here would construct the declaration twice, once in
    this process and once in uvicorn's, and a declaration is not something to build for a
    question about its shape.
    """
    try:
        module = ast.parse(entry_point.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return False
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return True
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return True
    return False


def _dev_agent_name(args: Namespace) -> str:
    """Return the name this agent runs under while developing.

    ``--name``, or the directory's own name. The agent itself does not carry one: the name is
    its identity on the broker, in telemetry and in its routes, and who supplies it depends on
    who is hosting it -- a group image's map, a single-agent image's Dockerfile, or this.

    Raises:
        SystemExit: if neither yields a legal namespace, because a repaired name would be a
            different agent under the same directory.
    """
    requested = (getattr(args, "name", "") or "").strip() or Path.cwd().name
    candidate = re.sub(r"[-\s]+", "_", requested).lower()
    try:
        return validate_namespace(candidate)
    except ValueError as exc:
        print(f"Error: '{requested}' cannot be an agent name: {exc}", file=sys.stderr)
        print("Pass --name with a name matching [a-z][a-z0-9_]*", file=sys.stderr)
        sys.exit(1)


def _temporary_agent_map(args: Namespace) -> Path:
    """Write a one-agent map for this run and point the framework at it.

    Written outside the project on purpose. Writing an ``agents.toml`` into the directory would
    leave behind exactly the file an agent must not carry, and a developer who then committed it
    would have an agent that names itself.
    """
    name = _dev_agent_name(args)
    handle = tempfile.NamedTemporaryFile("w", suffix="-agents.toml", delete=False, encoding="utf-8")
    with handle as written:
        written.write(f'[agents.{name}]\nroot   = "."\nmodule = "src.main:agent"\n')
    path = Path(handle.name)
    os.environ[AGENT_MAP_ENV] = str(path)
    atexit.register(lambda: path.unlink(missing_ok=True))
    print(f"No {AGENT_MAP_FILE} here, which is how an agent directory should look.")
    print(f"Serving it as '{name}' (from {'--name' if getattr(args, 'name', '') else 'the directory name'}).")
    print(f"Its routes are under /api/{name}.")
    return path
