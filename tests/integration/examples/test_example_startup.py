"""Startup verification tests for all examples.

These tests verify that each example can be imported and initialized without errors.
"""

import pytest
import sys
from pathlib import Path
import importlib.util


EXAMPLES_DIR = Path(__file__).parent.parent.parent.parent / "examples"


def load_example_app(example_name: str, main_path: Path):
    """Dynamically load an example's app.

    Args:
        example_name: Name of the example
        main_path: Path to the main.py file

    Returns:
        The loaded app or create_app function
    """
    # Add example to path
    if main_path.parent.name == "src":
        sys.path.insert(0, str(main_path.parent.parent))
    else:
        sys.path.insert(0, str(main_path.parent))

    # Load the module
    spec = importlib.util.spec_from_file_location(f"{example_name}_main", main_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{example_name}_main"] = module

    try:
        spec.loader.exec_module(module)
        return module
    except Exception as e:
        pytest.fail(f"Failed to load {example_name}: {e}")


def test_rest_microservice_startup():
    """Test that rest_microservice can start."""
    example_path = EXAMPLES_DIR / "rest_microservice"
    main_path = example_path / "src" / "main.py"

    module = load_example_app("rest_microservice", main_path)

    # Verify app was created
    assert hasattr(module, "app"), "rest_microservice should export 'app'"
    assert module.app is not None


def test_simple_event_processor_startup():
    """Test that simple_event_processor can start."""
    example_path = EXAMPLES_DIR / "simple_event_processor"
    main_path = example_path / "src" / "main.py"

    module = load_example_app("simple_event_processor", main_path)

    # Verify app was created
    assert hasattr(module, "app"), "simple_event_processor should export 'app'"
    assert module.app is not None


def test_complex_agent_startup():
    """Test that complex_agent can start."""
    example_path = EXAMPLES_DIR / "complex_agent"
    main_path = example_path / "src" / "main.py"

    module = load_example_app("complex_agent", main_path)

    # Verify app was created
    assert hasattr(module, "app"), "complex_agent should export 'app'"
    assert module.app is not None


def test_customer_support_qa_startup():
    """Test that customer_support_qa can start."""
    example_path = EXAMPLES_DIR / "customer_support_qa"
    main_path = example_path / "src" / "main.py"

    module = load_example_app("customer_support_qa", main_path)

    # Verify app was created
    assert hasattr(module, "app"), "customer_support_qa should export 'app'"
    assert module.app is not None


def test_scheduler_example_startup():
    """Test that scheduler_example can start."""
    example_path = EXAMPLES_DIR / "scheduler_example"
    main_path = example_path / "src" / "main.py"

    module = load_example_app("scheduler_example", main_path)

    # Verify app was created
    assert hasattr(module, "app"), "scheduler_example should export 'app'"
    assert module.app is not None


def test_trivia_game_startup():
    """Test that trivia_game can start."""
    example_path = EXAMPLES_DIR / "trivia_game"
    main_path = example_path / "src" / "main.py"

    module = load_example_app("trivia_game", main_path)

    # Verify app was created
    assert hasattr(module, "app"), "trivia_game should export 'app'"
    assert module.app is not None


def test_sessions_job_processor_startup():
    """Test that sessions_job_processor can start."""
    example_path = EXAMPLES_DIR / "sessions_job_processor"
    main_path = example_path / "main.py"

    module = load_example_app("sessions_job_processor", main_path)

    # Verify create_app function exists
    assert hasattr(module, "create_app"), "sessions_job_processor should export 'create_app'"

    # Try to create the app
    app = module.create_app()
    assert app is not None
