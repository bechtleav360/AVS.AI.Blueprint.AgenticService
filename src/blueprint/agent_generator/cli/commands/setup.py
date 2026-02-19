"""Setup command - create new Blueprint Agents project using the generator."""

import json
import logging
import sys
import tempfile
from argparse import Namespace
from pathlib import Path

from ...generator.generator import AgentGenerator
from ...generator.part_generators.part_generator_base import PartGeneratorBase

logger = logging.getLogger(__name__)


def create_basic_config(name: str) -> dict:
    """Create a basic configuration template.

    Args:
        name: Name of the microservice

    Returns:
        Configuration dictionary for the generator
    """
    return {
        "name": name,
        "description": f"{name} agent microservice",
        "communication_layer": {
            "rest_api": {
                "add_rest_api": True,
                "name": f"{name}Api",
                "description": f"REST API for {name}",
                "uses_services": [f"{name}Service"],
                "dto_classes": {
                    f"{name}RequestDTO": {
                        "description": f"Request DTO for {name}",
                        "fields": {
                            "id": {"type": "str", "description": "An ID", "default": "id"},
                            "data": {"type": "dict", "description": "A data field"},
                        },
                    },
                    f"{name}ResponseDTO": {
                        "description": f"Response DTO for {name}",
                        "fields": {
                            "id": {"type": "str", "description": "An ID", "default": "id"},
                            "data": {"type": "dict", "description": "A data field"},
                        },
                    },
                },
                "endpoint_functions": {
                    "request": {
                        "input_dto": f"{name}RequestDTO",
                        "output_dto": f"{name}ResponseDTO",
                        "service": f"{name}Service",
                        "method": "POST",
                    }
                },
                "mapper": {
                    "name": f"{name}Mapper",
                    "mappings": [
                        {
                            "from": {"name": f"{name}RequestDTO", "type": "dto"},
                            "to": {"name": f"{name}Model", "type": "domain_model"},
                            "field_mappings": {"id": "id", "data": "data"},
                        },
                        {
                            "from": {"name": f"{name}Model", "type": "domain_model"},
                            "to": {"name": f"{name}ResponseDTO", "type": "dto"},
                            "field_mappings": {"id": "id", "data": "data"},
                        },
                    ],
                },
            },
            "handlers": {f"{name}Handler": {"description": f"Handler for {name}", "priority": 10, "uses_services": [f"{name}Service"]}},
        },
        "agent_layer": {f"{name}Agent": {"runtime_name": f"{PartGeneratorBase.camel_to_snake(name)}_agent"}},
        "service_layer": {
            f"{name}Service": {
                "description": f"Service for {name}",
                "uses_agents": [f"{name}Agent"],
                "uses_domain_models": [f"{name}Model"],
                "process_function": {"name": "process_something", "input_type": f"{name}Model", "output_type": f"{name}Model"},
            }
        },
        "domain_models": {
            f"{name}Model": {
                "description": f"Domain model for {name}",
                "fields": {
                    "id": {"type": "str", "description": "An ID", "default": "id"},
                    "data": {"type": "dict", "description": "A data field"},
                },
            }
        },
    }


def run(args: Namespace) -> None:
    """Execute the setup command.

    Args:
        args: Parsed command-line arguments
    """
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    print("=== Blueprint Agents Project Setup ===")
    print("This will create a complete project structure with handlers, services, APIs, and agents.")

    # Get project name
    project_name = args.project_name
    output_dir = Path(args.output_dir).absolute()
    project_path = output_dir / project_name

    # Check if output directory exists
    if not output_dir.exists():
        print(f"Error: Output directory does not exist: {output_dir}", file=sys.stderr)
        sys.exit(1)

    # Check if project already exists
    if project_path.exists() and not args.overwrite:
        print(f"Error: Project directory already exists: {project_path}", file=sys.stderr)
        print("Use --overwrite to overwrite existing files", file=sys.stderr)
        sys.exit(1)

    print(f"\nCreating project: {project_name}")
    print(f"Location: {project_path}")

    try:
        # Create basic configuration
        config = create_basic_config(project_name)

        # Create a temporary config file for the generator
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
            config_file = f.name

        try:
            # Use the AgentGenerator to create the project
            generator = AgentGenerator(config_file, str(output_dir))
            generator.load_config()
            generator.generate()

            print("\n✓ Project created successfully!")
            print("\nProject structure:")
            print(f"  {project_name}/")
            print("  ├── src/")
            print("  │   ├── main.py")
            print("  │   ├── handlers/")
            print("  │   ├── services/")
            print("  │   ├── api/")
            print("  │   ├── models/")
            print("  │   └── prompts/")
            print("  ├── settings.toml")
            print("  ├── Dockerfile")
            print("  └── .gitignore")

            print("\nNext steps:")
            print(f"  1. cd {project_name}")
            print("  2. Review and edit the generated files")
            print("  3. Add your LLM API key to settings.toml:")
            print(f"     [runtimes.{PartGeneratorBase.camel_to_snake(project_name)}_agent]")
            print('     model_api_key = "your-api-key-here"')
            print("  4. Install dependencies: pip install -e .")
            print("  5. Run the service: uvicorn src.main:app --reload")
            print("  6. View API docs at: http://localhost:8000/docs")

        finally:
            # Clean up temporary config file
            Path(config_file).unlink(missing_ok=True)

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error generating project: {e}", file=sys.stderr)
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)
