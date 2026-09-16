"""Scaffold the image-level files: the agent map, the process settings and the group Dockerfile.

The other half of ``asbs setup``. These two modes write disjoint sets of files because they
describe different things: an *agent* is a directory of code, settings and prompts, and an
*image* is a container for some number of agents plus the map naming them. Conflating them is
what put an ``agents.toml`` inside every scaffolded agent -- a file that says which agents an
image contains, sitting inside one of them.

Nothing here names an agent, and no agent is created. Which agents an image contains is decided
one ``asbs setup <name>`` at a time, in whatever directories the author chooses, and recorded in
the map by hand. The map therefore starts empty, and a group with no agents refuses to start
rather than binding a port and consuming nothing.
"""

import sys
from argparse import Namespace
from pathlib import Path

BASE_FILES = Path(__file__).resolve().parent.parent.parent / "base_files"

GROUP_SETTINGS = """# The image's own settings: the keys that describe the *process*.
#
# One process has one of each of these, so they belong here rather than in any agent's
# settings.toml. An agent that sets one has it dropped before its settings are merged, with a
# warning naming the value the process uses instead.

[default]
app_name = "agent-group"
app_host = "0.0.0.0"
app_port = 8000
log_level = "INFO"

# "dapr" or "nats". One process speaks one bus.
# event_bus = "nats"

# Required once any agent registers a scheduler. "in_process" runs a timer in every replica and
# claims each tick through the cache, so it needs a cache; "event" takes the tick as an event.
# scheduler_mode = "event"

[development]
app_environment = "development"
log_level = "DEBUG"
"""


def scaffold_group(output_dir: Path, overwrite: bool) -> None:
    """Write the image-level files into ``output_dir``.

    Args:
        output_dir: Where the image is assembled -- the top of the repository, normally.
        overwrite: Replace files that are already there. Off by default, because this command
            is run in a directory that usually holds work already.
    """
    sources = {
        "agents.toml": BASE_FILES / "group_agents_toml.txt",
        "Dockerfile": BASE_FILES / "group_Dockerfile",
        ".gitignore": BASE_FILES / "template_for_git_ignore.txt",
    }

    written: list[str] = []
    skipped: list[str] = []
    for name, source in sources.items():
        target = output_dir / name
        if target.exists() and not overwrite:
            skipped.append(name)
            continue
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        written.append(name)

    settings = output_dir / "settings.toml"
    if settings.exists() and not overwrite:
        skipped.append("settings.toml")
    else:
        settings.write_text(GROUP_SETTINGS, encoding="utf-8")
        written.append("settings.toml")

    _report(output_dir, written, skipped)


def _report(output_dir: Path, written: list[str], skipped: list[str]) -> None:
    """Print what was written, and the one thing the author has to do next."""
    print("=== Blueprint Agents Group Setup ===")
    print(f"Location: {output_dir}")
    print("")
    print("Written:")
    for name in written:
        print(f"  + {name}")
    if skipped:
        print("")
        print("Left alone (use --overwrite to replace):")
        for name in skipped:
            print(f"  = {name}")

    print("")
    print("These are the image's files, not an agent's.")
    print("")
    print("agents.toml is empty: this image contains no agents yet, and a group with none")
    print("cannot start. Create each agent in its own directory:")
    print("")
    print("  mkdir -p agents/some_topic/my_agent")
    print("  cd agents/some_topic/my_agent")
    print("  asbs setup my_agent")
    print("")
    print("then add it to agents.toml, both keys required:")
    print("")
    print("  [agents.my_agent]")
    print('  root   = "agents/some_topic/my_agent"')
    print('  module = "agents.some_topic.my_agent.src.main:agent"')
    print("")
    print("An agent directory carries no agents.toml of its own, which is what lets it be")
    print("built as its own single-agent image without editing anything.")
    print("")
    print("Run 'asbs validate --group' here to check the map against what is on disk.")


def run(args: Namespace) -> None:
    """Execute ``asbs setup --group``.

    Args:
        args: Parsed command-line arguments.
    """
    output_dir = Path(args.output_dir).absolute()
    if not output_dir.is_dir():
        print(f"Error: Output directory does not exist: {output_dir}", file=sys.stderr)
        sys.exit(1)
    scaffold_group(output_dir, overwrite=args.overwrite)
