"""
Windsurf subcommand — generate Windsurf rules and workflows for a Blueprint Agents project.

Usage:
    windsurf [output_dir] [--overwrite]

If output_dir is not provided, the current working directory is used.
"""

import argparse
import logging
import os
import sys

from .generator.windsurf_generator import WindsurfGenerator


def main() -> None:
    """Entry point for the ``windsurf`` CLI command."""
    parser = argparse.ArgumentParser(
        prog="windsurf",
        description=(
            "Generate Windsurf rules and workflow files for a Blueprint Agents project.\n\n"
            "Creates (or updates) the .windsurf/ directory in the target project with:\n"
            "  .windsurf/rules/      — always-on context rules for Cascade\n"
            "  .windsurf/workflows/  — slash-command workflows (/create-rest-api, etc.)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        default=os.getcwd(),
        help="Root directory of the target project (default: current directory)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=False,
        help="Overwrite existing files (default: skip files that already exist)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    output_dir = os.path.abspath(args.output_dir)

    if not os.path.isdir(output_dir):
        print(f"Error: output directory does not exist: {output_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Generating Windsurf resources for project: {output_dir}")

    try:
        generator = WindsurfGenerator(output_dir)
        generator.generate(overwrite=args.overwrite)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
