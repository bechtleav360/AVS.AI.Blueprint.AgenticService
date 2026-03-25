"""Create command - scaffold individual components using existing generators."""

import logging
import re
import sys
from argparse import Namespace
from pathlib import Path

from ...generator.part_generators import (
    HandlerPartGenerator,
    ServicePartGenerator,
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

    # Convert name to proper format
    handler_name = args.name
    if not handler_name.endswith("Handler"):
        handler_name = f"{handler_name}Handler"

    handler_name_snake = _to_snake_case(handler_name.replace("Handler", ""))
    file_name = f"{handler_name_snake}_handler.py"
    output_file = output_dir / file_name

    if output_file.exists():
        print(f"Error: File already exists: {output_file}", file=sys.stderr)
        sys.exit(1)

    # Create minimal config for generator
    config = {
        "name": "cli_generated",
        "communication_layer": {
            "handlers": {
                handler_name: {
                    "description": f"Handler for {event_type} events",
                    "priority": args.priority,
                    "uses_services": [],
                }
            }
        },
    }

    # Use the generator to generate the content
    template_dir = _get_template_dir()
    generator = HandlerPartGenerator(config=config, template_dir=template_dir, src_path="src/handlers", handler_name=handler_name)

    # Read the template and apply replacements
    template_file = template_dir / "src" / "handlers" / "handler.txt"
    template_content = template_file.read_text()

    # Apply template variable replacements
    for key, value in generator.template_vars.items():
        template_content = template_content.replace(key, value)

    # Write to output file
    output_file.write_text(template_content)

    print(f"✓ Created handler: {output_file}")
    print("\nNext steps:")
    print(f"  1. Edit {output_file} to implement your logic")
    print("  2. Add to src/handlers/__init__.py:")
    print(f"     from .{file_name[:-3]} import {handler_name}")
    print("  3. Register in src/main.py:")
    print(f"     .with_handler({handler_name}())")


def create_service(args: Namespace) -> None:
    """Create a BusinessService component using ServicePartGenerator."""
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Convert name to proper format
    service_name = args.name
    if not service_name.endswith("Service"):
        service_name = f"{service_name}Service"

    service_name_snake = _to_snake_case(service_name.replace("Service", ""))
    file_name = f"{service_name_snake}.py"
    output_file = output_dir / file_name

    if output_file.exists():
        print(f"Error: File already exists: {output_file}", file=sys.stderr)
        sys.exit(1)

    # Create minimal config for generator
    config = {
        "name": "cli_generated",
        "service_layer": {
            service_name: {
                "description": f"Service for {service_name} operations",
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
    generator = ServicePartGenerator(config=config, template_dir=template_dir, src_path="src/services", service_name=service_name)

    # Read the template and apply replacements
    template_file = template_dir / "src" / "services" / "service.txt"
    template_content = template_file.read_text()

    # Apply template variable replacements
    for key, value in generator.template_vars.items():
        template_content = template_content.replace(key, value)

    # Write to output file
    output_file.write_text(template_content)

    print(f"✓ Created service: {output_file}")
    print("\nNext steps:")
    print(f"  1. Edit {output_file} to implement your business logic")
    print("  2. Add to src/services/__init__.py:")
    print(f"     from .{file_name[:-3]} import {service_name}")
    print("  3. Register in src/main.py:")
    print(f"     .with_service({service_name}())")


def create_api(args: Namespace) -> None:
    """Create a RestApi component.

    Note: API generation with full endpoints is complex.
    This creates a simple template file with placeholder endpoints.
    """
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Convert name to proper format
    api_name = args.name
    if not api_name.endswith("Api"):
        api_name = f"{api_name}Api"

    api_name_snake = _to_snake_case(api_name.replace("Api", ""))
    file_name = f"{api_name_snake}_api.py"
    output_file = output_dir / file_name

    if output_file.exists():
        print(f"Error: File already exists: {output_file}", file=sys.stderr)
        sys.exit(1)

    # Simple template for API (generators require complex endpoint config)
    code = f'''"""REST API for {api_name_snake} operations."""

import logging

from fastapi import HTTPException, status
from pydantic import BaseModel

from blueprint.agents.base import RestApi


logger = logging.getLogger(__name__)


# TODO: Define your request/response models here
class {api_name}Request(BaseModel):
    """Request model for {api_name_snake} operations."""
    # TODO: Add your fields
    # Example: name: str
    # Example: description: str | None = None
    pass


class {api_name}Response(BaseModel):
    """Response model for {api_name_snake} operations."""
    # TODO: Add your fields
    # Example: id: str
    # Example: name: str
    # Example: status: str
    pass


class {api_name}(RestApi):
    """REST API for {api_name_snake} operations."""

    def __init__(self, name: str = "{api_name_snake}") -> None:
        """Initialize the API.

        Args:
            name: Component name for registry
        """
        super().__init__(name=name)

        # TODO: Initialize service dependencies
        # Example: self._service = None (will be set in on_startup)

    async def on_startup(self) -> None:
        """Initialize the API."""
        logger.info("Starting %s API", self.get_name())

        # TODO: Get services from registry
        # Example: self._service = self.get_registry().get_service("{api_name_snake}_service")

        # Register routes
        self._register_routes()

    async def on_shutdown(self) -> None:
        """Cleanup when shutting down."""
        logger.info("Shutting down %s API", self.get_name())

    def _register_routes(self) -> None:
        """Register API routes."""

        @self.router.get("/{{item_id}}", response_model={api_name}Response)
        async def get_item(item_id: str) -> {api_name}Response:
            """Get item by ID."""
            try:
                # TODO: Implement get logic
                # Example: item = await self._service.get_by_id(item_id)
                # Example: if not item:
                # Example:     raise HTTPException(status_code=404, detail="Item not found")
                # Example: return {api_name}Response(**item)

                # Placeholder implementation
                return {api_name}Response(id=item_id, name="Sample item", status="active")

            except Exception as e:
                logger.exception("Error getting item")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to get item: {{e}}"
                )

        @self.router.post("/", response_model={api_name}Response)
        async def create_item(request: {api_name}Request) -> {api_name}Response:
            """Create new item."""
            try:
                # TODO: Implement create logic
                # Example: item = await self._service.create(request.dict())
                # Example: return {api_name}Response(**item)

                # Placeholder implementation
                import uuid
                return {api_name}Response(
                    id=str(uuid.uuid4()),
                    name=request.name if hasattr(request, 'name') else "New item",
                    status="created"
                )

            except Exception as e:
                logger.exception("Error creating item")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to create item: {{e}}"
                )
'''

    output_file.write_text(code)

    print(f"✓ Created API: {output_file}")
    print("\nNext steps:")
    print(f"  1. Edit {output_file} to add your endpoints")
    print("  2. Add to src/api/__init__.py:")
    print(f"     from .{file_name[:-3]} import {api_name}")
    print("  3. Register in src/main.py:")
    print(f"     .with_rest_api({api_name}())")
    print("  4. View docs at http://localhost:8000/docs")


def create_agent(args: Namespace) -> None:
    """Create an AgentRuntime component.

    Note: Agent generation is not yet implemented with generators.
    This creates a simple template file.
    """
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Convert name to proper format
    agent_name = args.name
    if agent_name.endswith("Agent"):
        agent_name = agent_name[:-5]

    _agent_class_name = f"{agent_name}Agent"
    agent_name_snake = _to_snake_case(agent_name)
    file_name = f"{agent_name_snake}_agent.py"
    output_file = output_dir / file_name

    if output_file.exists():
        print(f"Error: File already exists: {output_file}", file=sys.stderr)
        sys.exit(1)

    # Simple template for agent (generators don't support agents yet)
    code = f'''"""AgentRuntime for {agent_name_snake} operations."""

import logging

from blueprint.agents.agent import AgentBuilder
from blueprint.agents.base import AgentRuntime


logger = logging.getLogger(__name__)


def build_{agent_name_snake}_agent(config) -> AgentRuntime:
    """Build the {agent_name_snake} agent.

    Args:
        config: Application configuration

    Returns:
        Configured AgentRuntime instance
    """
    agent = (
        AgentBuilder(config, runtime_name="{agent_name_snake}")
        .with_model_from_config()
        .with_system_prompt()  # Auto-loads from config
        .build()
    )

    return agent
'''

    output_file.write_text(code)

    print(f"✓ Created agent: {output_file}")
    print("\nNext steps:")
    print(f"  1. Edit {output_file} to configure your agent")
    print(f"  2. Create prompt file: src/prompts/{agent_name_snake}_system.prompt")
    print("  3. Add to src/agents/__init__.py:")
    print(f"     from .{file_name[:-3]} import build_{agent_name_snake}_agent")
    print("  4. Register in src/main.py:")
    print(f"     .with_agent(build_{agent_name_snake}_agent(config))")
    print("  5. Add agent config to settings.toml:")
    print(f"     [runtimes.{agent_name_snake}]")
    print('     model_name = "gpt-4o-mini"')


def create_scheduler(args: Namespace) -> None:
    """Create a Scheduler component.

    Note: Scheduler generation is not yet implemented with generators.
    This creates a simple template file.
    """
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Convert name to proper format
    scheduler_name = args.name
    if not scheduler_name.endswith("Scheduler"):
        scheduler_name = f"{scheduler_name}Scheduler"

    scheduler_name_snake = _to_snake_case(scheduler_name.replace("Scheduler", ""))
    file_name = f"{scheduler_name_snake}_scheduler.py"
    output_file = output_dir / file_name

    if output_file.exists():
        print(f"Error: File already exists: {output_file}", file=sys.stderr)
        sys.exit(1)

    # Simple template for scheduler (generators don't support schedulers yet)
    code = f'''"""Scheduler for {scheduler_name_snake} operations."""

import logging

from blueprint.agents.base import Scheduler


logger = logging.getLogger(__name__)


class {scheduler_name}(Scheduler):
    """Scheduler for {scheduler_name_snake} operations."""

    def __init__(self, name: str = "{scheduler_name_snake}", cron_expression: str = "{args.cron}") -> None:
        """Initialize the scheduler.

        Args:
            name: Component name for registry
            cron_expression: Cron expression for scheduling
        """
        super().__init__(name=name, cron_expression=cron_expression)

        # TODO: Initialize scheduler-specific state
        # Example: self._processing_service = None

    async def on_startup(self) -> None:
        """Initialize the scheduler."""
        logger.info("Starting %s scheduler with cron: %s", self.get_name(), self.cron_expression)

        # TODO: Get services from registry
        # Example: self._processing_service = self.get_registry().get_service("processing_service")

    async def on_shutdown(self) -> None:
        """Cleanup when shutting down."""
        logger.info("Shutting down %s scheduler", self.get_name())

    async def tick(self) -> None:
        """Execute scheduled task."""
        logger.info("Running %s scheduler tick", self.get_name())

        try:
            # TODO: Implement your scheduled task here
            # Example: Process pending items
            # Example: await self._processing_service.process_pending_items()

            logger.info("Completed %s scheduler tick", self.get_name())

        except Exception as e:
            logger.exception("Error during %s scheduler tick", self.get_name())
            raise
'''

    output_file.write_text(code)

    print(f"✓ Created scheduler: {output_file}")
    print("\nNext steps:")
    print(f"  1. Edit {output_file} to implement tick() logic")
    print("  2. Add to src/schedulers/__init__.py:")
    print(f"     from .{file_name[:-3]} import {scheduler_name}")
    print("  3. Register in src/main.py:")
    print(f"     .with_scheduler({scheduler_name}())")
    print(f"\nCron expression: {args.cron}")
