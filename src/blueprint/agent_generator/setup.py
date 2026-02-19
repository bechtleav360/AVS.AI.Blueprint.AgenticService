"""
Setup command for creating agent microservice configuration files.

Can be used as:
    python -m blueprint.agent_generator.setup
    uv init
"""

import json
import sys
from pathlib import Path

from .generator.part_generators.part_generator_base import PartGeneratorBase


def create_basic_config(name: str) -> dict:
    """Create a basic configuration template."""
    return {
        "name": name,
        "description": f"{name} agent microservice",
        "communication_layer": {
            "rest_api": {
                "add_rest_api": True,
                "name": f"{name}RESTApi",
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


def main():
    """Create a basic configuration file and prompt for editing."""
    print("=== Agent Microservice Configuration Setup ===")
    print("This will create a basic configuration file that you can edit.")

    # Get the microservice name
    name = input("\nEnter a name for your microservice (e.g., CustomerSupport): ").strip()
    if not name:
        print("Error: A name is required.", file=sys.stderr)
        sys.exit(1)

    # Create the config file name
    config_file = f"setup_config.json"

    # Create basic config
    config = create_basic_config(name)

    # Write the config file with proper encoding
    abs_path = str(Path(config_file).absolute())
    try:
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error writing configuration file: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\nConfiguration file created at: {abs_path}")
    print("\nNext steps:")
    print(f"1. Edit the configuration file: {abs_path}. Multiple services, handlers and agents can be added.")
    print(f'2. Run: "create" to generate the src code structure, gitignore and Dockerfile.')


if __name__ == "__main__":
    main()
