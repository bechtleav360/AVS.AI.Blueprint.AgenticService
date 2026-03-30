"""Claude command - generate Claude Code integration files."""

import logging
import os
import sys
from argparse import Namespace

from ...generator.claude_generator import ClaudeGenerator

logger = logging.getLogger(__name__)


def run(args: Namespace) -> None:
    """Execute the claude command.

    Args:
        args: Parsed command-line arguments
    """
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    output_dir = os.path.abspath(args.output_dir)

    if not os.path.isdir(output_dir):
        print(f"Error: Output directory does not exist: {output_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Generating Claude Code integration files for: {output_dir}")

    try:
        generator = ClaudeGenerator(output_dir)
        generator.generate(overwrite=args.overwrite)

        print("\nCreated:")
        print("  .claude/CLAUDE.md                          - Blueprint framework context")
        print("  .claude/agents/blueprint-architect.md      - Architecture planning agent")
        print("  .claude/agents/blueprint-builder.md        - Component implementation agent")
        print("  .claude/skills/new-agent-service/SKILL.md  - /new-agent-service command")
        print("  .claude/skills/add-component/SKILL.md      - /add-component command")

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)
