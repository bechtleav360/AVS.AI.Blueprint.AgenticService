"""Docs command - locate the framework documentation shipped inside the package.

The guides ship with the package rather than being fetched from the web, so a developer
or an AI assistant working against the framework can read them offline. They land in
``blueprint/agent_generator/docs/``, which is somewhere under ``site-packages`` and not a
path anybody should have to type. This command resolves it.
"""

import importlib.resources
import sys
from argparse import Namespace
from pathlib import Path


def locate_docs_root() -> Path:
    """Return the directory holding the packaged documentation.

    Returns:
        Absolute path to the packaged ``docs/`` directory.

    Raises:
        FileNotFoundError: If the directory is missing, which means the package was
            built without its documentation.
    """
    try:
        pkg_ref = importlib.resources.files("blueprint.agent_generator")
        resolved = Path(str(pkg_ref)) / "docs"
        if resolved.is_dir():
            return resolved.resolve()
    except (TypeError, ModuleNotFoundError):
        pass

    # Fallback for running from a source checkout without an editable install
    fallback = Path(__file__).parent.parent.parent / "docs"
    if fallback.is_dir():
        return fallback.resolve()

    raise FileNotFoundError(
        "Could not locate the packaged documentation.\n"
        "Expected it at: blueprint/agent_generator/docs/\n"
        "This package was built without its docs; reinstall avs-blueprint-agents."
    )


def list_topics(root: Path) -> list[str]:
    """List every documentation page, as slugs relative to the docs root.

    Args:
        root: The packaged documentation directory.

    Returns:
        Sorted slugs such as ``guides/multi-agent-setup`` and ``concepts/caching``.
    """
    return sorted(p.relative_to(root).with_suffix("").as_posix() for p in root.rglob("*.md"))


def resolve_topic(root: Path, topic: str) -> Path:
    """Resolve a topic slug to a page on disk.

    Accepts a full slug (``guides/multi-agent-setup``), the same with a ``.md``
    suffix, or a bare page name (``multi-agent-setup``) when it is unambiguous.

    Args:
        root: The packaged documentation directory.
        topic: What the caller asked for.

    Returns:
        Absolute path to the page.

    Raises:
        FileNotFoundError: If nothing matches, or a bare name matches several pages.
    """
    slug = topic.removesuffix(".md").strip("/")

    exact = root / f"{slug}.md"
    if exact.is_file():
        return exact.resolve()

    matches = [t for t in list_topics(root) if t.rsplit("/", 1)[-1] == slug]
    if len(matches) == 1:
        return (root / f"{matches[0]}.md").resolve()
    if len(matches) > 1:
        raise FileNotFoundError(f"'{topic}' is ambiguous; it matches: {', '.join(matches)}")

    raise FileNotFoundError(f"No documentation page named '{topic}'. Run 'asbs docs' to list them.")


def run(args: Namespace) -> None:
    """Execute the docs command.

    Args:
        args: Parsed command-line arguments.
    """
    try:
        root = locate_docs_root()
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "root", False):
        print(root)
        return

    if not args.topic:
        print(f"Documentation root: {root}\n")
        print("Pages (read one with 'asbs docs <topic>'):\n")
        for slug in list_topics(root):
            print(f"  {slug}")
        return

    try:
        page = resolve_topic(root, args.topic)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.cat:
        print(page.read_text(encoding="utf-8"))
    else:
        print(page)
