"""Setup command - create new Blueprint Agents project using the generator."""

import json
import logging
import sys
import tempfile
from argparse import Namespace
from pathlib import Path
from typing import Any

from ...generator.generator import AgentGenerator
from ...generator.part_generators.part_generator_base import PartGeneratorBase
from . import group_setup

logger = logging.getLogger(__name__)


def create_basic_config(name: str) -> dict[str, Any]:
    """Create a basic configuration template.

    Args:
        name: Name of the microservice

    Returns:
        Configuration dictionary for the generator
    """
    # Avoid double "Agent" suffix when project name already ends with "agent"
    name_normalized = name.lower().replace("-", "").replace("_", "")
    has_agent_suffix = name_normalized.endswith("agent")
    agent_class_name = name if has_agent_suffix else f"{name}Agent"
    agent_runtime_name = PartGeneratorBase.camel_to_snake(name) if has_agent_suffix else f"{PartGeneratorBase.camel_to_snake(name)}_agent"

    return {
        "name": name,
        "component_name": name,
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
        "agent_layer": {agent_class_name: {"runtime_name": agent_runtime_name}},
        "service_layer": {
            f"{name}Service": {
                "description": f"Service for {name}",
                "uses_agents": [name if has_agent_suffix else f"{name}Agent"],
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

    # Two modes writing disjoint sets of files, because they describe different things: an
    # agent is a directory of code, settings and prompts; an image is a container for some
    # number of agents plus the map naming them.
    if getattr(args, "group", False):
        group_setup.run(args)
        return

    print("=== Blueprint Agents Project Setup ===")
    print("This will create a complete project structure with handlers, services, APIs, and agents.")

    # The name is this agent's *identity*, not a directory to create.
    #
    # `asbs` is installed into the project's own virtual environment, so by the time it can be
    # run at all the project directory exists and somebody is standing in it. Scaffolding into a
    # `<Name>/` subdirectory would put the source one level below the environment that has to
    # import it. The name is what `create_basic_config` derives everything else from: `app_name`,
    # the agent namespace in `agents.toml`, the class names and the prompt filenames.
    #
    # This used to compute a `project_path = output_dir / project_name`, guard `--overwrite`
    # with it and print it as the location -- while handing the generator `output_dir`. So the
    # directory it protected was never created, and the location it printed was never written to.
    if not args.project_name:
        print("Error: asbs setup needs the agent's name, or --group to create the image's files", file=sys.stderr)
        sys.exit(1)

    project_name = PartGeneratorBase.to_class_name(args.project_name)
    output_dir = Path(args.output_dir).absolute()

    if not output_dir.exists():
        print(f"Error: Output directory does not exist: {output_dir}", file=sys.stderr)
        sys.exit(1)

    existing = [path.name for path in (output_dir / "src", output_dir / "settings.toml") if path.exists()]
    if existing and not args.overwrite:
        print(f"Error: {output_dir} already contains a scaffolded project ({', '.join(existing)})", file=sys.stderr)
        print("Use --overwrite to write over it", file=sys.stderr)
        sys.exit(1)

    print(f"\nScaffolding agent: {project_name}")
    print(f"Location: {output_dir}")

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
            print(f"  {output_dir.name}/   (this directory)")
            print("  ├── src/")
            print("  │   ├── main.py")
            print("  │   ├── handlers/")
            print("  │   ├── services/")
            print("  │   ├── api/")
            print("  │   ├── models/")
            print("  │   └── prompts/")
            print("  ├── tests/")
            print("  ├── settings.toml")
            print("  ├── .secrets.toml")
            print("  ├── Dockerfile")
            print("  └── .gitignore")

            namespace = PartGeneratorBase.agent_namespace(config)
            print("\nNext steps:")
            print("  1. Review and edit the generated files")
            print("  2. Add your LLM API key to .secrets.toml")
            print("     (A .secrets.toml with a placeholder has been created for you)")
            print("  3. Run the generated tests: pytest")
            print("  4. Run the service: asbs dev")
            print(f"  5. View API docs at: http://localhost:8000/docs (this agent's routes are under /api/{namespace})")

            print("\nsrc/main.py declares this agent; it does not build an application.")
            print("\nThis directory carries no agents.toml, and that is deliberate: the agent map says")
            print("which agents an *image* contains, so an agent holding one would be an agent that")
            print("knows whether it is running alone. Whoever hosts it supplies the name:")
            print("  - its own Dockerfile serves it directly with uvicorn src.main:create_app --factory")
            print("  - a group image maps it in the repository's agents.toml, with root and module")
            print("  - asbs dev uses this directory's name unless --name says otherwise")
            print("\nThat name is the agent's identity on the broker, in telemetry and in its routes")
            print("(/api/<name>) -- change it now if you are going to, because changing it after the")
            print("first deploy is a consumer migration.")
            print("\nTo host it in a group, add to the repository's agents.toml:")
            print(f"  [agents.{namespace}]")
            print('  root   = "<path from that file to this directory>"')
            print('  module = "<that path as a dotted package>.src.main:agent"')

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
