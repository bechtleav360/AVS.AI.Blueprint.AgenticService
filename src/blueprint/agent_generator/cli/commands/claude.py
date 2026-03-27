"""Claude command - generate a CLAUDE.md for Claude Code integration."""

import importlib.resources
import logging
import sys
from argparse import Namespace
from pathlib import Path

logger = logging.getLogger(__name__)

_CLAUDE_MD = "CLAUDE.md"


def _locate_template() -> Path:
    """Locate the CLAUDE.md template inside the installed package.

    Uses ``importlib.resources`` so the path is resolved correctly from
    both an editable install and a built wheel.

    Returns:
        Path to the CLAUDE.md template file.

    Raises:
        FileNotFoundError: If the template cannot be located.
    """
    try:
        pkg_ref = importlib.resources.files("blueprint.agent_generator")
        candidate = Path(str(pkg_ref)) / "assistant_integrations" / _CLAUDE_MD
        if candidate.exists():
            return candidate.resolve()
    except (TypeError, ModuleNotFoundError):
        pass

    # Fallback for running from source without an editable install
    fallback = Path(__file__).parent.parent.parent / "assistant_integrations" / _CLAUDE_MD
    if fallback.exists():
        return fallback.resolve()

    raise FileNotFoundError(
        f"Could not locate the {_CLAUDE_MD} template.\n"
        "Expected it at: blueprint.agent_generator/assistant_integrations/CLAUDE.md\n"
        "Make sure the package is installed with: pip install -e ."
    )


def run(args: Namespace) -> None:
    """Execute the claude command.

    Args:
        args: Parsed command-line arguments.
    """
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    output_dir = Path(args.output_dir).resolve()

    if not output_dir.is_dir():
        print(f"Error: Output directory does not exist: {output_dir}", file=sys.stderr)
        sys.exit(1)

    destination = output_dir / _CLAUDE_MD

    if destination.exists() and not args.overwrite:
        print(f"Error: {destination} already exists.", file=sys.stderr)
        print("Use --overwrite to replace it.", file=sys.stderr)
        sys.exit(1)

    try:
        template = _locate_template()
        destination.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
        logger.info("Wrote %s", destination)

        print(f"\n✓ {_CLAUDE_MD} generated in: {output_dir}")
        print("\nClaude Code will pick it up automatically on the next session.")

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)