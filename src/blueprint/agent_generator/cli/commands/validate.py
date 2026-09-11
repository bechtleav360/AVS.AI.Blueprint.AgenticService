"""Validate command - check project structure and configuration."""

import logging
import sys
import tomllib
from argparse import Namespace
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

IDEMPOTENCY_NOTICE = "\n".join(
    [
        "Event deduplication is off ('idempotency_enabled' is not set), so every handler in",
        "    this project can be run more than once for the same event. Delivery is at-least-once:",
        "    a lost acknowledgement, a pod restart or a rolling deploy each produce a redelivery,",
        "    after the first attempt has already committed its side effects.",
        "    Decide which one this project needs:",
        "      - handlers that are safe to repeat -- nothing to change; or",
        "      - set 'idempotency_enabled = true' and 'idempotency_ttl = <seconds>' in settings.toml,",
        "        with a window that outlasts the broker redelivery window.",
    ]
)


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
    notices = []

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

        # Check if main.py uses AppBuilder. Nothing is checked about Config here: main.py is a
        # declaration, and the configuration belongs to whatever builds it -- a main.py that
        # mentions Config at all is the pre-declaration shape, not the expected one.
        content = main_file.read_text()
        if "AppBuilder" not in content:
            warnings.append("src/main.py does not appear to use AppBuilder")

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

    # Idempotency decision (spec sec. 7.4): the framework must not choose for the author,
    # so it says nothing at all only when the project has no handlers to run twice.
    notice = _idempotency_notice(project_dir)
    if notice:
        notices.append(notice)

    # Print summary
    print()
    print("=" * 60)

    if notices:
        print(f"\nNotices ({len(notices)}):")
        for item in notices:
            print(f"  - {item}")

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


def _idempotency_notice(project_dir: Path) -> str | None:
    """Return the dedup notice if this project has handlers and has not opted into dedup.

    Returns ``None`` when the project declares ``idempotency_enabled``, whichever way it
    declares it: the author has then made the decision spec sec. 7.4 asks for, and saying
    it again on every run is how a notice stops being read. Also ``None`` when there are no
    handlers, since nothing can be dispatched twice.
    """
    handlers_dir = project_dir / "src" / "handlers"
    if not handlers_dir.is_dir() or not any(handlers_dir.glob("*_handler.py")):
        return None

    settings_file = project_dir / "settings.toml"
    if not settings_file.is_file():
        return IDEMPOTENCY_NOTICE

    try:
        with settings_file.open("rb") as handle:
            settings = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        # A settings file that cannot be read is reported by its own check; guessing at the
        # dedup setting from an unparseable file would be worse than staying quiet.
        logger.debug("Could not read settings.toml for the idempotency check: %s", exc)
        return None

    # Dynaconf environments are top-level tables, and the key is valid in any of them.
    if _declares_idempotency(settings):
        return None
    return IDEMPOTENCY_NOTICE


def _declares_idempotency(settings: dict[str, Any]) -> bool:
    """Report whether ``idempotency_enabled`` appears at the top level or in any environment."""
    if "idempotency_enabled" in settings:
        return True
    return any(isinstance(value, dict) and "idempotency_enabled" in value for value in settings.values())
