"""Validate command - check project structure and configuration."""

import logging
import sys
from argparse import Namespace
from pathlib import Path

logger = logging.getLogger(__name__)


def run(args: Namespace) -> None:
    """Execute the validate command.

    Args:
        args: Parsed command-line arguments
    """
    project_dir = Path(args.project_dir).resolve()

    if not project_dir.is_dir():
        print(f"Error: Project directory does not exist: {project_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Validating Blueprint Agents project: {project_dir}")
    print()

    issues = []
    warnings = []

    # Check for required directories
    required_dirs = ["src", "tests"]
    for dir_name in required_dirs:
        dir_path = project_dir / dir_name
        if not dir_path.is_dir():
            issues.append(f"Missing required directory: {dir_name}/")
        else:
            print(f"✓ Found {dir_name}/")

    # Check for configuration files
    config_files = ["settings.toml", "pyproject.toml"]
    for file_name in config_files:
        file_path = project_dir / file_name
        if not file_path.is_file():
            issues.append(f"Missing configuration file: {file_name}")
        else:
            print(f"✓ Found {file_name}")

    # Check for secrets template
    secrets_example = project_dir / "secrets.toml.example"
    secrets_file = project_dir / "secrets.toml"
    if not secrets_example.is_file():
        warnings.append("Missing secrets.toml.example template")
    else:
        print("✓ Found secrets.toml.example")

    if not secrets_file.is_file():
        warnings.append("Missing secrets.toml (copy from secrets.toml.example)")

    # Check for main.py
    main_file = project_dir / "src" / "main.py"
    if not main_file.is_file():
        issues.append("Missing src/main.py entry point")
    else:
        print("✓ Found src/main.py")

        # Check if main.py uses AppBuilder
        content = main_file.read_text()
        if "AppBuilder" not in content:
            warnings.append("src/main.py does not appear to use AppBuilder")
        if "Config" not in content:
            warnings.append("src/main.py does not appear to use Config")

    # Check for component directories
    component_dirs = ["handlers", "services", "api", "models"]
    src_dir = project_dir / "src"
    if src_dir.is_dir():
        for dir_name in component_dirs:
            dir_path = src_dir / dir_name
            if dir_path.is_dir():
                print(f"✓ Found src/{dir_name}/")

    # Check for tests
    tests_dir = project_dir / "tests"
    if tests_dir.is_dir():
        test_files = list(tests_dir.glob("test_*.py"))
        if not test_files:
            warnings.append("No test files found in tests/")
        else:
            print(f"✓ Found {len(test_files)} test file(s)")

    # Check for Docker files
    dockerfile = project_dir / "Dockerfile"
    docker_compose = project_dir / "docker-compose.yml"
    if dockerfile.is_file():
        print("✓ Found Dockerfile")
    else:
        warnings.append("Missing Dockerfile for containerization")

    if docker_compose.is_file():
        print("✓ Found docker-compose.yml")

    # Print summary
    print()
    print("=" * 60)

    if not issues and not warnings:
        print("✓ Validation passed! Project structure looks good.")
        sys.exit(0)

    if warnings:
        print(f"\n⚠ Warnings ({len(warnings)}):")
        for warning in warnings:
            print(f"  - {warning}")

    if issues:
        print(f"\n✗ Issues ({len(issues)}):")
        for issue in issues:
            print(f"  - {issue}")
        print("\nProject validation failed. Please fix the issues above.")
        sys.exit(1)
    else:
        print("\n✓ Validation passed with warnings.")
        sys.exit(0)
