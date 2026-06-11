"""Create command - scaffold individual components using existing generators."""

import logging
import re
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any

from ...generator.part_generators import (
    HandlerPartGenerator,
    ServicePartGenerator,
)
from ..utils.naming_utils import (
    normalize_component_name,
    add_import_to_main,
    add_component_registration_to_main,
    read_main_py,
    write_main_py,
)

logger = logging.getLogger(__name__)


def _get_template_dir() -> Path:
    """Get the template directory path.

    Returns:
        Path to the base_files directory
    """
    return Path(__file__).parent.parent.parent / "base_files"


def _to_snake_case(name: str) -> str:
    """Convert CamelCase to snake_case.

    Args:
        name: CamelCase string

    Returns:
        snake_case string
    """
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def run(args: Namespace) -> None:
    """Execute the create command.

    Args:
        args: Parsed command-line arguments
    """
    if not args.component:
        print("Error: No component type specified", file=sys.stderr)
        print("Available: handler, service, api, agent, scheduler", file=sys.stderr)
        sys.exit(1)

    if args.component == "handler":
        create_handler(args)
    elif args.component == "service":
        create_service(args)
    elif args.component == "api":
        create_api(args)
    elif args.component == "agent":
        create_agent(args)
    elif args.component == "scheduler":
        create_scheduler(args)
    else:
        print(f"Error: Unknown component type: {args.component}", file=sys.stderr)
        sys.exit(1)


def create_handler(args: Namespace) -> None:
    """Create an EventHandler component using HandlerPartGenerator."""
    # Prompt for event type if not provided
    event_type = args.event_type
    if not event_type:
        event_type = input("Event type to handle (e.g., 'order.placed'): ").strip()
        if not event_type:
            print("Error: Event type is required", file=sys.stderr)
            sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Use naming utilities to normalize the handler name
    class_name, snake_name, file_name = normalize_component_name(args.name, "handler")

    module_name = file_name[:-3]  # Remove .py extension
    output_file = output_dir / file_name

    if output_file.exists():
        print(f"Error: File already exists: {output_file}", file=sys.stderr)
        sys.exit(1)

    # Validate project root has reasonable structure
    project_root = Path.cwd()

    # Create minimal config for generator
    config: dict[str, Any] = {
        "name": "cli_generated",
        "communication_layer": {
            "handlers": {
                class_name: {
                    "description": f"Handler for {event_type} events",
                    "priority": args.priority,
                    "uses_services": [],
                }
            }
        },
    }

    # Use the generator to generate the content
    template_dir = _get_template_dir()
    generator = HandlerPartGenerator(
        config=config,
        template_dir=template_dir,
        src_path="src/handlers",
        handler_name=class_name,
    )

    # Read the template and apply replacements
    template_file = template_dir / "src" / "handlers" / "handler.txt"
    template_content = template_file.read_text()

    # Apply template variable replacements
    for key, value in generator.template_vars.items():
        template_content = template_content.replace(key, value)

    # Write to output file
    output_file.write_text(template_content)

    print(f"✓ Created handler: {output_file}")

    # Attempt to auto-register in main.py
    auto_registered = False
    try:
        main_content = read_main_py(project_root)

        # Add import statement (use snake_case module name)
        import_statement = f"from src.handlers.{module_name} import {class_name}"
        main_content = add_import_to_main(main_content, import_statement, "handler")

        # Add component registration
        main_content = add_component_registration_to_main(main_content, class_name, "handler")

        # Write updated main.py
        write_main_py(project_root, main_content)

        auto_registered = True
        print("✓ Auto-registered in src/main.py")
        print(f"  - Added import: from src.handlers.{module_name} import {class_name}")
        print(f"  - Added registration: .with_handler({class_name}())")

    except (FileNotFoundError, ValueError) as e:
        logger.debug("Could not auto-register handler: %s", e)
    except Exception as e:
        logger.warning("Unexpected error during auto-registration: %s", e)

    if not auto_registered:
        print("\n⚠ Could not auto-register (src/main.py not found or invalid)")
        print("Please register manually:")

    print("\nNext steps:")
    print(f"  1. Edit {output_file} to implement your logic")
    print("  2. Add to src/handlers/__init__.py:")
    print(f"     from .{module_name} import {class_name}")
    if not auto_registered:
        print("  3. Add to src/main.py:")
        print(f"     .with_handler({class_name}())")


def create_service(args: Namespace) -> None:
    """Create a BusinessService component using ServicePartGenerator."""
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Use naming utilities to normalize the service name
    class_name, snake_name, file_name = normalize_component_name(args.name, "service")

    module_name = file_name[:-3]  # Remove .py extension
    output_file = output_dir / file_name

    if output_file.exists():
        print(f"Error: File already exists: {output_file}", file=sys.stderr)
        sys.exit(1)

    # Create minimal config for generator
    config: dict[str, Any] = {
        "name": "cli_generated",
        "service_layer": {
            class_name: {
                "description": f"Service for {snake_name} operations",
                "uses_domain_models": [],
                "uses_agents": [],
                "process_function": {
                    "name": "process",
                    "input_type": "InputData",
                    "output_type": "OutputData",
                },
            }
        },
    }

    # Use the generator to generate the content
    template_dir = _get_template_dir()
    generator = ServicePartGenerator(
        config=config,
        template_dir=template_dir,
        src_path="src/services",
        service_name=class_name,
    )

    # Read the template and apply replacements
    template_file = template_dir / "src" / "services" / "service.txt"
    template_content = template_file.read_text()

    # Apply template variable replacements
    for key, value in generator.template_vars.items():
        template_content = template_content.replace(key, value)

    # Write to output file
    output_file.write_text(template_content)

    print(f"✓ Created service: {output_file}")

    # Attempt to auto-register in main.py
    auto_registered = False
    project_root = Path.cwd()
    try:
        main_content = read_main_py(project_root)

        # Add import statement (use snake_case module name)
        import_statement = f"from src.services.{module_name} import {class_name}"
        main_content = add_import_to_main(main_content, import_statement, "service")

        # Add component registration
        main_content = add_component_registration_to_main(main_content, class_name, "service")

        # Write updated main.py
        write_main_py(project_root, main_content)

        auto_registered = True
        print("✓ Auto-registered in src/main.py")
        print(f"  - Added import: from src.services.{module_name} import {class_name}")
        print(f"  - Added registration: .with_service({class_name}())")

    except (FileNotFoundError, ValueError) as e:
        logger.debug("Could not auto-register service: %s", e)
    except Exception as e:
        logger.warning("Unexpected error during auto-registration: %s", e)

    if not auto_registered:
        print("\n⚠ Could not auto-register (src/main.py not found or invalid)")
        print("Please register manually:")

    print("\nNext steps:")
    print(f"  1. Edit {output_file} to implement your business logic")
    print("  2. Add to src/services/__init__.py:")
    print(f"     from .{module_name} import {class_name}")
    if not auto_registered:
        print("  3. Add to src/main.py:")
        print(f"     .with_service({class_name}())")


def create_api(args: Namespace) -> None:
    """Create a RestApi component with separate models file.

    Generates four files:
    - API class file in src/api/
    - DTO file in src/models/{name}/dto.py
    - Domain models file in src/models/{name}/domain_models.py
    - Mapper file in src/models/{name}/mapper.py
    """
    api_output_dir = Path(args.output_dir)
    api_output_dir.mkdir(parents=True, exist_ok=True)

    # Use naming utilities to normalize the API name
    class_name, _, file_name = normalize_component_name(args.name, "api")

    module_name = file_name[:-3]  # Remove .py extension
    api_output_file = api_output_dir / file_name

    if api_output_file.exists():
        print(f"Error: File already exists: {api_output_file}", file=sys.stderr)
        sys.exit(1)

    # Create models directory if needed
    project_root = Path.cwd()
    models_dir = project_root / "src" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    # Generate models file in a subfolder named after the component
    # e.g., for "order_management_api" we create "src/models/order_management/dto.py"
    base_name = module_name.replace("_api", "")
    component_models_dir = models_dir / base_name
    component_models_dir.mkdir(parents=True, exist_ok=True)
    models_file = component_models_dir / "dto.py"
    models_module_name = f"{base_name}.dto"
    domain_models_file = component_models_dir / "domain_models.py"
    mapper_file = component_models_dir / "mapper.py"

    if models_file.exists():
        print(f"Error: File already exists: {models_file}", file=sys.stderr)
        sys.exit(1)
    if domain_models_file.exists():
        print(f"Error: File already exists: {domain_models_file}", file=sys.stderr)
        sys.exit(1)
    if mapper_file.exists():
        print(f"Error: File already exists: {mapper_file}", file=sys.stderr)
        sys.exit(1)

    # Generate request/response class names
    base_class_name = class_name.replace("Api", "")
    request_class_name = f"{base_class_name}Request"
    response_class_name = f"{base_class_name}Response"
    domain_model_class_name = f"{base_class_name}Model"
    mapper_class_name = f"{base_class_name}Mapper"

    # Generate models file content
    models_code = f'''"""Pydantic models for {base_name} API."""

from pydantic import BaseModel


class {request_class_name}(BaseModel):
    """Request model for {base_name} operations."""

    # TODO: Add your request fields
    # Example: name: str
    # Example: description: str | None = None
    pass


class {response_class_name}(BaseModel):
    """Response model for {base_name} operations."""

    # TODO: Add your response fields
    # Example: id: str
    # Example: name: str
    # Example: status: str
    pass
'''

    domain_models_code = f'''"""Domain models for {base_name}."""

from pydantic import BaseModel


class {domain_model_class_name}(BaseModel):
    """{base_class_name} domain model."""

    # TODO: Add your domain model fields
    # Example: id: str
    # Example: name: str
    pass
'''

    mapper_code = f'''"""Mapper between DTOs and domain models for {base_name}."""

from .dto import {request_class_name}, {response_class_name}
from .domain_models import {domain_model_class_name}


class {mapper_class_name}:
    """Static mapper class for converting between domain models and DTOs."""

    @staticmethod
    def from_{_to_snake_case(request_class_name)}({_to_snake_case(request_class_name)}: {request_class_name}) -> {domain_model_class_name}:
        # TODO: Map request DTO fields to domain model
        raise NotImplementedError()

    @staticmethod
    def to_{_to_snake_case(response_class_name)}({_to_snake_case(domain_model_class_name)}: {domain_model_class_name}) -> {response_class_name}:
        # TODO: Map domain model fields to response DTO
        raise NotImplementedError()
'''

    # Generate API file content
    # Use base_name for cleaner docstrings (without "_api" suffix)
    api_code = f'''"""REST API for {base_name} operations."""

from __future__ import annotations

import logging

from fastapi import HTTPException, status

from blueprint.agents.io.api.rest_api_base import RestApiBase

from src.models.{models_module_name} import {request_class_name}, {response_class_name}


logger = logging.getLogger(__name__)


class {class_name}(RestApiBase):
    """REST API for {base_name} operations."""

    def __init__(self) -> None:
        """Initialize the API."""
        super().__init__()
        self._service = None

    async def on_startup(self) -> None:
        """Initialize the API."""

        # TODO: Get services from registry
        # Example: self._service = self.registry.get_service("some_service")

    async def on_shutdown(self) -> None:
        """Cleanup when shutting down."""

    @RestApiBase.get("/{{item_id}}", response_model={response_class_name})
    async def get_item(self, item_id: str) -> {response_class_name}:
        """Get item by ID."""
        try:
            # TODO: Implement get logic
            # Example: item = await self._service.get_by_id(item_id)
            # Example: if not item:
            # Example:     raise HTTPException(status_code=404, detail="Item not found")
            # Example: return {response_class_name}(**item)

            # Placeholder implementation
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Implement get logic"
            )

        except Exception as e:
            logger.exception("Error getting item: %s", e)
            raise

    @RestApiBase.post("/", response_model={response_class_name})
    async def create_item(self, request: {request_class_name}) -> {response_class_name}:
        """Create new item."""
        try:
            # TODO: Implement create logic
            # Example: item = await self._service.create(request.model_dump())
            # Example: return {response_class_name}(**item)

            # Placeholder implementation
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Implement create logic"
            )

        except Exception as e:
            logger.exception("Error creating item: %s", e)
            raise
'''

    # Write models files
    models_file.write_text(models_code)
    print(f"✓ Created dto: {models_file}")

    domain_models_file.write_text(domain_models_code)
    print(f"✓ Created domain models: {domain_models_file}")

    mapper_file.write_text(mapper_code)
    print(f"✓ Created mapper: {mapper_file}")

    # Write API file
    api_output_file.write_text(api_code)
    print(f"✓ Created API: {api_output_file}")

    # Attempt to auto-register in main.py
    auto_registered = False
    try:
        main_content = read_main_py(project_root)

        # Add models import (use snake_case module name)
        models_import_statement = f"from src.models.{models_module_name} import {request_class_name}, {response_class_name}"
        main_content = add_import_to_main(main_content, models_import_statement, "api")

        # Add API import (use snake_case module name)
        api_import_statement = f"from src.api.{module_name} import {class_name}"
        main_content = add_import_to_main(main_content, api_import_statement, "api")

        # Add component registration
        main_content = add_component_registration_to_main(main_content, class_name, "api")

        # Write updated main.py
        write_main_py(project_root, main_content)

        auto_registered = True
        print("✓ Auto-registered in src/main.py")
        print(f"  - Added import: from src.models.{models_module_name} import {request_class_name}, {response_class_name}")
        print(f"  - Added import: from src.api.{module_name} import {class_name}")
        print(f"  - Added registration: .with_rest_api({class_name}())")

    except (FileNotFoundError, ValueError) as e:
        logger.debug("Could not auto-register API: %s", e)
    except Exception as e:
        logger.warning("Unexpected error during auto-registration: %s", e)

    if not auto_registered:
        print("\n⚠ Could not auto-register (src/main.py not found or invalid)")
        print("Please register manually:")

    print("\nNext steps:")
    print(f"  1. Edit {domain_models_file} to define your domain model fields")
    print(f"  2. Edit {models_file} to define your request/response DTO fields")
    print(f"  3. Edit {mapper_file} to implement the mapping logic")
    print(f"  4. Edit {api_output_file} to implement your endpoints")
    print("  5. Add to src/api/__init__.py:")
    print(f"     from .{module_name} import {class_name}")
    if not auto_registered:
        print("  6. Add to src/main.py:")
        print(f"     from src.models.{models_module_name} import {request_class_name}, {response_class_name}")
        print(f"     from src.api.{module_name} import {class_name}")
        print(f"     .with_rest_api({class_name}())")
    print("  6. View docs at http://localhost:8000/docs")


def create_agent(args: Namespace) -> None:
    """Create an AgentRuntime component with prompts and settings.

    Creates four things:
    1. Agent module file in src/agents/
    2. System prompt file in src/prompts/
    3. Instruction prompt file in src/prompts/
    4. Configuration in settings.toml

    And auto-registers in main.py.
    """

    # Use naming utilities to normalize the agent name
    class_name, snake_name, file_name = normalize_component_name(args.name, "agent")

    module_name = file_name[:-3]  # Remove .py extension

    # Get project root and directories
    project_root = Path.cwd()
    prompts_dir = project_root / "src" / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    # Define prompt file paths
    system_prompt_file = prompts_dir / f"{snake_name}_system.prompt"
    instruction_prompt_file = prompts_dir / f"{snake_name}_instruction.prompt"

    # Check if prompt files already exist
    if system_prompt_file.exists():
        print(f"Error: File already exists: {system_prompt_file}", file=sys.stderr)
        sys.exit(1)

    if instruction_prompt_file.exists():
        print(f"Error: File already exists: {instruction_prompt_file}", file=sys.stderr)
        sys.exit(1)

    # Create system prompt content
    system_prompt_content = f"""You are a {snake_name} AI agent.

Your role is to perform {snake_name} operations with precision and clarity.

Be concise, precise, and professional in your responses. Follow best practices and provide explanations when appropriate."""

    # Create instruction prompt content
    instruction_prompt_content = f"""Process the following request for {snake_name} operations:

{{user_input}}

Provide a clear and actionable response."""

    # Write system prompt file
    system_prompt_file.write_text(system_prompt_content)
    print(f"✓ Created system prompt: {system_prompt_file}")

    # Write instruction prompt file
    instruction_prompt_file.write_text(instruction_prompt_content)
    print(f"✓ Created instruction prompt: {instruction_prompt_file}")

    # Update settings.toml with agent configuration
    settings_file = project_root / "settings.toml"

    try:
        if settings_file.exists():
            settings_content = settings_file.read_text(encoding="utf-8")
        else:
            settings_content = '[default]\napp_name = "generated-agent"\n\n'

        # Check if runtime section already exists
        runtime_section = f"[default.runtimes.{snake_name}]"
        if runtime_section not in settings_content:
            # Add runtime configuration
            settings_content += f"\n{runtime_section}\n"
            settings_content += 'model_provider = "openai"\n'
            settings_content += 'model_name = "gpt-5-mini"\n'
            settings_content += "model_temperature = 0.7\n"
            settings_content += "model_max_tokens = 2000\n"

            settings_models_section = f"[default.runtimes.{snake_name}.models]"
            if settings_models_section not in settings_content:
                settings_content += f"\n{settings_models_section}\n"
                settings_content += 'openai_reasoning_effort = "gpt-5-mini"\n'
                settings_content += 'openai_reasoning_summary = "detailed"\n'

            settings_file.write_text(settings_content, encoding="utf-8")
            print("✓ Updated settings.toml with runtime config")
        else:
            print(f"⚠ Runtime [{runtime_section}] already exists in settings.toml")

    except (OSError, FileNotFoundError) as e:
        logger.debug("Could not update settings.toml: %s", e)
        print(f"⚠ Could not update settings.toml: {e}")

    # Attempt to auto-register in main.py
    auto_registered = False
    try:
        main_content = read_main_py(project_root)

        agent_name = snake_name if snake_name.lower().endswith("agent") else snake_name + "_agent"

        # Add agent variable declaration (before AppBuilder)
        agent_var_declaration = f"""{agent_name}: AgentRuntime = (\n\tAgentBuilder(config=config, runtime_name="{agent_name}")
        .with_model_from_config()
        .with_system_prompt("{agent_name}_system")
        .build(name="{agent_name}")\n)\n"""

        # Insert the agent variable before the 'app = (' line
        lines = main_content.split("\n")
        app_builder_idx = -1
        for i, line in enumerate(lines):
            if line.strip().startswith("app = ("):
                app_builder_idx = i
                break

        if app_builder_idx >= 0:
            # Insert the agent variable declaration before the AppBuilder
            lines.insert(app_builder_idx, agent_var_declaration)
            main_content = "\n".join(lines)

        # Add component registration to AppBuilder
        # For agents, pass the variable name as instantiation (e.g., document_analyzer_agent)
        instantiation = f"{agent_name}"
        main_content = add_component_registration_to_main(main_content, agent_name, "agent", instantiation=instantiation)

        # Write updated main.py
        write_main_py(project_root, main_content)

        auto_registered = True
        print("✓ Auto-registered in src/main.py")
        print(f"  - Added import: from src.agents.{module_name} import build_{agent_name}")
        print(f"  - Added agent declaration: {agent_name}: AgentRuntime = build_{agent_name}(config)")
        print(f"  - Added registration: .with_agent({agent_name})")

    except (FileNotFoundError, ValueError) as e:
        logger.debug("Could not auto-register agent: %s", e)
    except Exception as e:
        logger.warning("Unexpected error during auto-registration: %s", e)

    if not auto_registered:
        print("\n⚠ Could not auto-register (src/main.py not found or invalid)")
        print("Please register manually:")

    print("\nNext steps:")
    print(f"  1. Edit {system_prompt_file} to refine the system prompt")
    print(f"  2. Edit {instruction_prompt_file} to add dynamic instruction templates")
    print("  3. Add to src/agents/__init__.py:")
    print(f"     from .{module_name} import build_{agent_name}")
    if not auto_registered:
        print("  4. Add to src/main.py (before app = (...)):")
        print(f"     {agent_name}: AgentRuntime = build_{agent_name}(config)")
        print("  5. Add to src/main.py AppBuilder chain:")
        print(f"     .with_agent({agent_name})")


def create_scheduler(args: Namespace) -> None:
    """Create a Scheduler component.

    Note: Scheduler generation is not yet implemented with generators.
    This creates a simple template file.
    """
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Use naming utilities to normalize the scheduler name
    class_name, snake_name, file_name = normalize_component_name(args.name, "scheduler")

    module_name = file_name[:-3]  # Remove .py extension
    output_file = output_dir / file_name

    if output_file.exists():
        print(f"Error: File already exists: {output_file}", file=sys.stderr)
        sys.exit(1)

    # Simple template for scheduler (generators don't support schedulers yet)
    code = f'''"""Scheduler for {snake_name.replace("_scheduler", "")} operations."""

import logging

from blueprint.agents.io.api.scheduling.scheduler import SchedulerBase


logger = logging.getLogger(__name__)


class {class_name}(SchedulerBase):
    """Scheduler for {snake_name.replace("_scheduler", "")} operations."""

    def __init__(self) -> None:
        """Initialize the scheduler.

        Args:
            name: Component name for registry (optional)
            crontab: Cron expression for scheduling
        """
        super().__init__(crontab="{args.cron}")

    async def on_startup(self) -> None:
        """Initialize the scheduler."""

        # TODO: Get services from registry
        # Example: self._service = self.registry.get_service(MyService)

    async def on_shutdown(self) -> None:
        """Cleanup when shutting down."""

    async def tick(self) -> None:
        """Execute scheduled task."""

        try:
            # TODO: Implement your scheduled task here
            # Example: await self._service.do_work()


        except Exception as e:
            logger.exception("Error during %s scheduler tick: %s", __name__, e)
            raise
'''

    output_file.write_text(code)

    print(f"✓ Created scheduler: {output_file}")

    # Attempt to auto-register in main.py
    auto_registered = False
    project_root = Path.cwd()
    try:
        main_content = read_main_py(project_root)

        # Add import statement (use snake_case module name)
        import_statement = f"from src.schedulers.{module_name} import {class_name}"
        main_content = add_import_to_main(main_content, import_statement, "scheduler")

        # Add component registration
        main_content = add_component_registration_to_main(main_content, class_name, "scheduler")

        # Write updated main.py
        write_main_py(project_root, main_content)

        auto_registered = True
        print("✓ Auto-registered in src/main.py")
        print(f"  - Added import: from src.schedulers.{module_name} import {class_name}")
        print(f"  - Added registration: .with_scheduler({class_name}())")

    except (FileNotFoundError, ValueError) as e:
        logger.debug("Could not auto-register scheduler: %s", e)
    except Exception as e:
        logger.warning("Unexpected error during auto-registration: %s", e)

    if not auto_registered:
        print("\n⚠ Could not auto-register (src/main.py not found or invalid)")
        print("Please register manually:")

    print("\nNext steps:")
    print(f"  1. Edit {output_file} to implement tick() logic")
    print("  2. Add to src/schedulers/__init__.py:")
    print(f"     from .{module_name} import {class_name}")
    if not auto_registered:
        print("  3. Add to src/main.py:")
        print(f"     .with_scheduler({class_name}())")
    print(f"\nCron expression: {args.cron}")
