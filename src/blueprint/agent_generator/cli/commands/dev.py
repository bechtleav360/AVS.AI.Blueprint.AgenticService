"""Dev command - start development server."""

import logging
import os
import subprocess
import sys
import tomllib
from argparse import Namespace
from pathlib import Path

logger = logging.getLogger(__name__)

AGENT_MAP_FILE = "agents.toml"
LEGACY_ENTRY_POINT = "src/main.py"

GROUP_FACTORY = "blueprint.agents.entrypoint:create_group_app"
LEGACY_APP = "src.main:app"

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
    if agent_map.is_file():
        command = _group_command(args, agent_map)
    elif Path(LEGACY_ENTRY_POINT).is_file():
        # A project scaffolded before the agent map existed still builds its own application in
        # src/main.py. It is served the way it always was, at the root namespace, because that
        # is the namespace it is deployed under too -- the two still agree.
        print(f"No {AGENT_MAP_FILE}; serving {LEGACY_APP} at the root namespace.")
        command = _legacy_command(args)
    else:
        print(f"Error: neither {AGENT_MAP_FILE} nor {LEGACY_ENTRY_POINT} found", file=sys.stderr)
        print("Make sure you're in a Blueprint Agents project directory", file=sys.stderr)
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
