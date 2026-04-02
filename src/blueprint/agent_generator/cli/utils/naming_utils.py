"""Naming and AST utilities for component generation."""

import re
from pathlib import Path


# ============================================================================
# Naming Conversion Functions
# ============================================================================


def get_component_suffix(component_type: str) -> str:
    """
    Get the naming suffix for a component type.

    Args:
        component_type: One of 'agent', 'service', 'handler', 'api', 'scheduler'

    Returns:
        The suffix to append to the component name
    """
    suffixes = {
        "agent": "agent",
        "service": "Service",
        "handler": "Handler",
        "api": "Api",
        "scheduler": "Scheduler",
    }
    return suffixes.get(component_type, "")


def to_class_name(name: str) -> str:
    """
    Convert any string to CamelCase (PascalCase) for class names.

    Handles:
    - snake_case → SnakeCase
    - kebab-case → KebabCase
    - Mixed cases → MixedCase
    - Already camelCase → CamelCase (unchanged)

    Args:
        name: Input string to convert

    Returns:
        CamelCase string suitable for class names
    """
    # Replace underscores and hyphens with spaces
    name = name.replace("_", " ").replace("-", " ")
    # Split on spaces and capitalize each word
    words = name.split()
    return "".join(word.capitalize() for word in words)


def camel_to_snake(name: str) -> str:
    """
    Convert CamelCase to snake_case.

    Args:
        name: CamelCase string

    Returns:
        snake_case string
    """
    # Insert underscore before capital letters (except first)
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    # Insert underscore before capital letters preceded by lowercase
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def to_snake_case(name: str) -> str:
    """Convert CamelCase to snake_case.

    Alias for camel_to_snake() for backward compatibility.

    Args:
        name: CamelCase string

    Returns:
        snake_case string
    """
    return camel_to_snake(name)


def normalize_component_name(
    name: str, component_type: str
) -> tuple[str, str, str]:
    """
    Normalize a component name according to naming conventions.

    Main naming function that handles all conversions:
    - Input 'test_agent' + 'agent' → ('TestAgent', 'test_agent', 'test_agent_agent.py')
    - Input 'TestAgent' + 'agent' → ('TestAgent', 'test_agent', 'test_agent_agent.py')
    - Input 'order_processor' + 'service' → ('OrderProcessorService', 'order_processor_service', 'order_processor_service.py')

    Args:
        name: Raw component name (can be snake_case, CamelCase, or kebab-case)
        component_type: One of 'agent', 'service', 'handler', 'api', 'scheduler'

    Returns:
        Tuple of (class_name, snake_name, filename)
        - class_name: CamelCase class name with appropriate suffix
        - snake_name: snake_case name for variable/import
        - filename: filename for the component module
    """
    # Step 1: Convert to snake_case
    snake_name_base = camel_to_snake(name)

    # Step 2: Get the suffix for this component type
    suffix = get_component_suffix(component_type)
    suffix_lower = suffix.lower()

    # Step 3: Build class name and snake_name
    class_name_base = to_class_name(snake_name_base)

    # Remove component_type suffix if already present in the input
    if suffix_lower:  # Only remove suffix if there is one
        if class_name_base.lower().endswith(suffix_lower):
            class_name_base = class_name_base[: -len(suffix)]
        if snake_name_base.lower().endswith(suffix_lower):
            snake_name_base = snake_name_base[: -len(suffix)]
            if snake_name_base.endswith("_") or snake_name_base.endswith("-"):
                snake_name_base = snake_name_base[:-1]

    # Build final class_name and snake_name with suffix if needed
    class_name = class_name_base + suffix
    snake_name = snake_name_base + ("_" + suffix_lower if suffix_lower else "")

    # Step 4: Build filename - always include the component_type in filename
    filename = snake_name_base + "_" + component_type + ".py"

    return (class_name, snake_name, filename)


# ============================================================================
# Main.py AST Modification Functions
# ============================================================================


def read_main_py(project_root: Path) -> str:
    """
    Read the main.py file from a project.

    Args:
        project_root: Root directory of the project

    Returns:
        Contents of main.py as a string
    """
    main_file = project_root / "src" / "main.py"
    return main_file.read_text(encoding="utf-8")


def write_main_py(project_root: Path, content: str) -> None:
    """
    Write content to the main.py file.

    Args:
        project_root: Root directory of the project
        content: Content to write to main.py
    """
    main_file = project_root / "src" / "main.py"
    main_file.write_text(content, encoding="utf-8")


def add_import_to_main(
    main_content: str, import_statement: str, component_type: str
) -> str:
    """
    Add an import statement to main.py in the appropriate section.

    Locates the import section and inserts the new import in the right place:
    - Imports from blueprint.agents core go after existing blueprint imports
    - Component imports (from src.handlers, src.services, etc.) go at the end

    Args:
        main_content: Current content of main.py
        import_statement: Import statement to add (e.g., "from src.handlers.order_handler import OrderHandler")
        component_type: One of 'agent', 'service', 'handler', 'api', 'scheduler'

    Returns:
        Updated main.py content with import added
    """
    lines = main_content.split("\n")

    # Find the last import line
    last_import_idx = -1
    for i, line in enumerate(lines):
        if line.startswith(("from ", "import ")):
            last_import_idx = i

    # Insert after the last import
    if last_import_idx >= 0:
        lines.insert(last_import_idx + 1, import_statement + "\n")
    else:
        # No imports found, insert at the beginning
        lines.insert(0, import_statement + "\n")

    return "\n".join(lines)


def extract_component_registrations(main_content: str) -> tuple[list[tuple[str, str]], int, int]:
    """
    Extract all component registrations from the AppBuilder chain.

    Finds and returns all .with_* method calls along with their line indices.

    Args:
        main_content: Content of main.py file

    Returns:
        Tuple of:
        - List of (component_type, full_line) tuples
        - Index of line with "AppBuilder("
        - Index of line with ".build()"
    """
    lines = main_content.split("\n")
    components = []
    app_builder_idx = -1
    build_idx = -1

    method_map = {
        "with_service": "service",
        "with_agent": "agent",
        "with_handler": "handler",
        "with_rest_api": "api",
        "with_scheduler": "scheduler",
        "with_cache": "cache",
    }

    for i, line in enumerate(lines):
        stripped = line.strip()

        if "AppBuilder(" in line:
            app_builder_idx = i

        if ".build()" in line:
            build_idx = i

        for method, comp_type in method_map.items():
            if stripped.startswith(f".{method}("):
                components.append((comp_type, line))
                break

    return components, app_builder_idx, build_idx


def sort_components(components: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """
    Sort components according to Framework dependency order.

    Order:
    1. Services
    2. Agents
    3. Handlers
    4. APIs
    5. Schedulers
    6. Cache (last)

    Args:
        components: List of (component_type, line) tuples

    Returns:
        Sorted list maintaining the same tuple structure
    """
    order = {
        "service": 0,
        "agent": 1,
        "handler": 2,
        "api": 3,
        "scheduler": 4,
        "cache": 5,
    }
    return sorted(components, key=lambda x: order.get(x[0], 999))


def add_component_registration_to_main(
    main_content: str,
    class_name: str,
    component_type: str,
    instantiation: str = "",
) -> str:
    """
    Add a component registration line to the AppBuilder chain in main.py.

    Extracts all existing components, adds the new component, and rebuilds the
    entire AppBuilder chain in correct dependency order:
    1. Services
    2. Agents
    3. Handlers
    4. REST APIs
    5. Schedulers
    6. Cache (if present)

    This ensures the chain is always in the correct order, even if it was
    previously out of order.

    Modifies the AppBuilder chain to include the new component:
    - For services: adds .with_service(ServiceClass())
    - For handlers: adds .with_handler(HandlerClass())
    - For APIs: adds .with_rest_api(ApiClass())
    - For schedulers: adds .with_scheduler(SchedulerClass())
    - For agents: adds .with_agent(agent_name)

    Args:
        main_content: Current content of main.py
        class_name: Name of the component class to register
        component_type: One of 'agent', 'service', 'handler', 'api', 'scheduler'
        instantiation: Optional custom instantiation code (defaults to ClassName())

    Returns:
        Updated main.py content with component registration added and chain re-ordered
    """
    # Determine the method name and default instantiation
    methods = {
        "service": "with_service",
        "handler": "with_handler",
        "api": "with_rest_api",
        "scheduler": "with_scheduler",
        "agent": "with_agent",
    }

    method_name = methods.get(component_type, "with_service")

    # Build the instantiation if not provided
    if not instantiation:
        if component_type == "agent":
            instantiation = class_name
        else:
            instantiation = f"{class_name}()"

    # Build the registration line for the new component
    new_registration_line = f"    .{method_name}({instantiation})"

    # Extract existing components and AppBuilder boundaries
    components, app_builder_idx, build_idx = extract_component_registrations(main_content)

    # Add the new component to the list
    components.append((component_type, new_registration_line))

    # Sort all components according to dependency order
    sorted_components = sort_components(components)

    # Rebuild the AppBuilder chain
    lines = main_content.split("\n")

    # Find the range of lines to replace (from after AppBuilder to before .build())
    if app_builder_idx < 0 or build_idx < 0:
        # Fallback for malformed code
        lines.append(new_registration_line)
        return "\n".join(lines)

    # Remove old component registrations
    new_lines = []
    for i, line in enumerate(lines):
        if i <= app_builder_idx:
            new_lines.append(line)
        elif i >= build_idx:
            new_lines.append(line)
        # Skip old component lines (they're between app_builder_idx and build_idx)

    # Insert sorted components between AppBuilder and .build()
    insert_point = app_builder_idx + 1
    for _, comp_line in sorted_components:
        new_lines.insert(insert_point, comp_line)
        insert_point += 1

    return "\n".join(new_lines)
