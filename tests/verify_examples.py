#!/usr/bin/env python3
"""Verify that all examples can start correctly.

This script attempts to start each example and verifies it initializes without errors.
"""

import subprocess
import sys
import time
from pathlib import Path
import signal


EXAMPLES_DIR = Path(__file__).parent.parent / "examples"

# Examples with their startup commands
EXAMPLES = {
    "rest_microservice": {
        "cwd": EXAMPLES_DIR / "rest_microservice",
        "cmd": [sys.executable, "-c", "from src.main import app; print('SUCCESS')"],
    },
    "simple_event_processor": {
        "cwd": EXAMPLES_DIR / "simple_event_processor",
        "cmd": [sys.executable, "-c", "from src.main import app; print('SUCCESS')"],
    },
    "complex_agent": {
        "cwd": EXAMPLES_DIR / "complex_agent",
        "cmd": [sys.executable, "-c", "from src.main import app; print('SUCCESS')"],
    },
    "customer_support_qa": {
        "cwd": EXAMPLES_DIR / "customer_support_qa",
        "cmd": [sys.executable, "-c", "from src.main import app; print('SUCCESS')"],
    },
    "scheduler_example": {
        "cwd": EXAMPLES_DIR / "scheduler_example",
        "cmd": [sys.executable, "-c", "from src.main import app; print('SUCCESS')"],
    },
    "trivia_game": {
        "cwd": EXAMPLES_DIR / "trivia_game",
        "cmd": [sys.executable, "-c", "from src.main import app; print('SUCCESS')"],
    },
    "sessions_job_processor": {
        "cwd": EXAMPLES_DIR / "sessions_job_processor",
        "cmd": [sys.executable, "-c", "from main import create_app; app = create_app(); print('SUCCESS')"],
    },
}


def verify_example(name: str, config: dict) -> tuple[bool, str]:
    """Verify an example can start.

    Args:
        name: Example name
        config: Configuration with cwd and cmd

    Returns:
        Tuple of (success, message)
    """
    try:
        # Set PYTHONPATH to include the src directory
        import os
        env = os.environ.copy()
        src_path = str(Path(__file__).parent / "src")
        env["PYTHONPATH"] = src_path + ":" + env.get("PYTHONPATH", "")

        result = subprocess.run(
            config["cmd"],
            cwd=config["cwd"],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )

        if result.returncode == 0 and "SUCCESS" in result.stdout:
            return True, "✓ Started successfully"
        else:
            error_msg = result.stderr if result.stderr else result.stdout
            return False, f"✗ Failed to start:\n{error_msg}"

    except subprocess.TimeoutExpired:
        return False, "✗ Timeout during startup"
    except Exception as e:
        return False, f"✗ Error: {str(e)}"


def main():
    """Run verification for all examples."""
    print("=" * 70)
    print("Verifying Example Startup")
    print("=" * 70)
    print()

    results = {}
    for name, config in EXAMPLES.items():
        print(f"Testing {name}...", end=" ", flush=True)
        success, message = verify_example(name, config)
        results[name] = (success, message)
        print(message)

    print()
    print("=" * 70)
    print("Summary")
    print("=" * 70)

    passed = sum(1 for success, _ in results.values() if success)
    failed = len(results) - passed

    print(f"Passed: {passed}/{len(results)}")
    print(f"Failed: {failed}/{len(results)}")

    if failed > 0:
        print("\nFailed examples:")
        for name, (success, message) in results.items():
            if not success:
                print(f"  - {name}: {message}")
        sys.exit(1)
    else:
        print("\n✓ All examples can start successfully!")
        sys.exit(0)


if __name__ == "__main__":
    main()
