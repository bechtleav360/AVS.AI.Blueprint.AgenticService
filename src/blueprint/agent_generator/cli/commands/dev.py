"""Dev command - start development server."""

import logging
import os
import sys
import subprocess
from argparse import Namespace
from pathlib import Path

logger = logging.getLogger(__name__)


def run(args: Namespace) -> None:
    """Execute the dev command.
    
    Args:
        args: Parsed command-line arguments
    """
    # Check if we're in a project directory
    if not Path("src/main.py").exists():
        print("Error: src/main.py not found", file=sys.stderr)
        print("Make sure you're in a Blueprint Agents project directory", file=sys.stderr)
        sys.exit(1)
    
    print(f"Starting development server on {args.host}:{args.port}")
    print("Press Ctrl+C to stop")
    print()
    
    try:
        # Run uvicorn with reload
        cmd = [
            "python",
            "-m",
            "uvicorn",
            "src.main:app",
            "--reload",
            "--host", args.host,
            "--port", str(args.port),
        ]
        
        subprocess.run(cmd, check=True)
        
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
