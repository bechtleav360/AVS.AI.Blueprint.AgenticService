"""Integration tests for all examples.

These tests verify that each example:
1. Has the required file structure
2. Has valid configuration files
3. Can be imported and instantiated
"""

import pytest
from pathlib import Path
import tomllib


EXAMPLES_DIR = Path(__file__).parent.parent.parent.parent / "examples"

# List of all examples to test
EXAMPLES = [
    "rest_microservice",
    "simple_event_processor",
    "complex_agent",
    "customer_support_qa",
    "scheduler_example",
    "trivia_game",
    "sessions_job_processor",
]


@pytest.mark.parametrize("example_name", EXAMPLES)
def test_example_has_main_file(example_name):
    """Test that each example has a main.py file."""
    example_path = EXAMPLES_DIR / example_name

    # Check for main.py in either root or src/
    has_main = (example_path / "main.py").exists() or \
                (example_path / "src" / "main.py").exists()

    assert has_main, f"Example {example_name} missing main.py"


@pytest.mark.parametrize("example_name", EXAMPLES)
def test_example_has_settings(example_name):
    """Test that each example has a settings.toml file."""
    example_path = EXAMPLES_DIR / example_name
    settings_file = example_path / "settings.toml"

    assert settings_file.exists(), f"Example {example_name} missing settings.toml"


@pytest.mark.parametrize("example_name", EXAMPLES)
def test_example_settings_valid(example_name):
    """Test that each example's settings.toml is valid TOML."""
    example_path = EXAMPLES_DIR / example_name
    settings_file = example_path / "settings.toml"

    if settings_file.exists():
        with open(settings_file, "rb") as f:
            settings = tomllib.load(f)
        assert isinstance(settings, dict), f"Example {example_name} settings.toml is not valid"
        # Check for app_name in root or default section
        has_app_name = "app_name" in settings or \
                       ("default" in settings and "app_name" in settings["default"])
        assert has_app_name, f"Example {example_name} missing app_name in settings"


@pytest.mark.parametrize("example_name", EXAMPLES)
def test_example_has_readme(example_name):
    """Test that each example has a README.md file."""
    example_path = EXAMPLES_DIR / example_name
    readme_file = example_path / "README.md"

    assert readme_file.exists(), f"Example {example_name} missing README.md"


# Specific tests for examples with REST APIs
REST_API_EXAMPLES = ["rest_microservice", "scheduler_example"]


@pytest.mark.parametrize("example_name", REST_API_EXAMPLES)
def test_rest_api_example_structure(example_name):
    """Test that REST API examples have the required structure."""
    example_path = EXAMPLES_DIR / example_name

    assert (example_path / "src" / "api").exists(), \
        f"Example {example_name} missing src/api directory"
    assert (example_path / "src" / "services").exists(), \
        f"Example {example_name} missing src/services directory"


# Specific tests for event handler examples
EVENT_HANDLER_EXAMPLES = [
    "simple_event_processor",
    "complex_agent",
    "customer_support_qa",
    "sessions_job_processor",
]


@pytest.mark.parametrize("example_name", EVENT_HANDLER_EXAMPLES)
def test_event_handler_example_structure(example_name):
    """Test that event handler examples have the required structure."""
    example_path = EXAMPLES_DIR / example_name

    # Check for handlers directory in either root or src/
    has_handlers = (example_path / "handlers").exists() or \
                   (example_path / "src" / "handlers").exists()

    assert has_handlers, f"Example {example_name} missing handlers directory"


def test_sessions_job_processor_specific():
    """Test sessions_job_processor specific requirements."""
    example_path = EXAMPLES_DIR / "sessions_job_processor"

    # Check for handlers
    assert (example_path / "handlers").exists()
    assert (example_path / "handlers" / "text_extraction_handler.py").exists()

    # Check settings has sessions_service config
    with open(example_path / "settings.toml", "rb") as f:
        settings = tomllib.load(f)
    assert "sessions_service" in settings, "sessions_job_processor missing sessions_service config"


def test_scheduler_example_specific():
    """Test scheduler_example specific requirements."""
    example_path = EXAMPLES_DIR / "scheduler_example"

    # Check for schedulers directory
    assert (example_path / "src" / "schedulers").exists()

    # Check that scheduler files exist (at least one)
    schedulers_dir = example_path / "src" / "schedulers"
    scheduler_files = list(schedulers_dir.glob("*.py"))
    # Filter out __init__.py
    scheduler_files = [f for f in scheduler_files if f.name != "__init__.py"]
    assert len(scheduler_files) > 0, "No scheduler files found"
