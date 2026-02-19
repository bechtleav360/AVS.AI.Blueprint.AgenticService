"""Windsurf command - generate Windsurf IDE integration files."""

import logging
import os
import sys
from argparse import Namespace

from ...generator.windsurf_generator import WindsurfGenerator

logger = logging.getLogger(__name__)


def run(args: Namespace) -> None:
    """Execute the windsurf command.
    
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
    
    print(f"Generating Windsurf integration files for: {output_dir}")
    
    try:
        generator = WindsurfGenerator(output_dir)
        generator.generate(overwrite=args.overwrite)
        
        print(f"\n✓ Windsurf files generated successfully!")
        print(f"\nCreated:")
        print(f"  .windsurf/rules/      - Always-on context rules")
        print(f"  .windsurf/workflows/  - Slash-command workflows")
        print(f"\nYou can now use Windsurf Cascade with:")
        print(f"  - Automatic context from rules")
        print(f"  - Slash commands like /create-handler")
        
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)
