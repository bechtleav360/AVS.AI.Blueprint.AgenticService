"""Main entry point for asbc (Agentic Service Blueprint Client) CLI."""

import argparse
import sys

from .commands import claude, create, dev, setup, validate


def main() -> None:
    """Entry point for the asbc CLI command."""
    parser = argparse.ArgumentParser(
        prog="asbs",
        description="Agentic Service Blueprint Shell - CLI for Blueprint Agents framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Setup command
    setup_parser = subparsers.add_parser(
        "setup",
        help="Create a new Blueprint Agents project",
        description="Scaffold a complete project structure with handlers, services, APIs, and configuration",
    )
    setup_parser.add_argument(
        "project_name",
        help="Name of the project to create (e.g., 'invoice-processor')",
    )
    setup_parser.add_argument(
        "--output-dir",
        default=".",
        help="Parent directory where project will be created (default: current directory)",
    )
    setup_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing files (default: skip existing files)",
    )
    setup_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    # Create command
    create_parser = subparsers.add_parser(
        "create",
        help="Scaffold individual components",
        description="Create handlers, services, APIs, agents, or schedulers",
    )
    create_subparsers = create_parser.add_subparsers(dest="component", help="Component type to create")

    # create handler
    handler_parser = create_subparsers.add_parser("handler", help="Create an EventHandler")
    handler_parser.add_argument("name", help="Handler name (e.g., 'OrderPlaced')")
    handler_parser.add_argument("--event-type", help="Event type to handle (e.g., 'order.placed')")
    handler_parser.add_argument("--priority", type=int, default=10, help="Handler priority (default: 10)")
    handler_parser.add_argument("--output-dir", default="src/handlers", help="Output directory")

    # create service
    service_parser = create_subparsers.add_parser("service", help="Create a BusinessService")
    service_parser.add_argument("name", help="Service name (e.g., 'Invoice')")
    service_parser.add_argument("--output-dir", default="src/services", help="Output directory")

    # create api
    api_parser = create_subparsers.add_parser("api", help="Create a RestApi")
    api_parser.add_argument("name", help="API name (e.g., 'Orders')")
    api_parser.add_argument("--output-dir", default="src/api", help="Output directory")

    # create agent
    agent_parser = create_subparsers.add_parser("agent", help="Create an AgentRuntime")
    agent_parser.add_argument("name", help="Agent name (e.g., 'InvoiceAnalyzer')")
    agent_parser.add_argument("--output-dir", default="src/agents", help="Output directory")

    # create scheduler
    scheduler_parser = create_subparsers.add_parser("scheduler", help="Create a Scheduler")
    scheduler_parser.add_argument("name", help="Scheduler name (e.g., 'DailyCleanup')")
    scheduler_parser.add_argument("--cron", default="0 * * * *", help="Cron expression (default: '0 * * * *')")
    scheduler_parser.add_argument("--output-dir", default="src/schedulers", help="Output directory")

    # Claude command
    claude_parser = subparsers.add_parser(
        "claude",
        help="Generate Claude Code integration files",
        description="Create .claude/CLAUDE.md with Blueprint framework context",
    )
    claude_parser.add_argument(
        "output_dir",
        nargs="?",
        default=".",
        help="Project root directory (default: current directory)",
    )
    claude_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing files",
    )
    claude_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    # Windsurf command
    windsurf_parser = subparsers.add_parser(
        "windsurf",
        help="Generate Windsurf IDE integration files",
        description="Create .windsurf/ directory with rules and workflows",
    )
    windsurf_parser.add_argument(
        "output_dir",
        nargs="?",
        default=".",
        help="Project root directory (default: current directory)",
    )
    windsurf_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing files",
    )
    windsurf_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    # Validate command
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate project structure and configuration",
        description="Check that project follows Blueprint Agents conventions",
    )
    validate_parser.add_argument(
        "project_dir",
        nargs="?",
        default=".",
        help="Project directory to validate (default: current directory)",
    )

    # Dev command
    dev_parser = subparsers.add_parser(
        "dev",
        help="Start development server",
        description="Run the application with hot reload",
    )
    dev_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to run on (default: 8000)",
    )
    dev_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )

    # Claude command
    claude_parser = subparsers.add_parser(
        "claude",
        help="Generate a CLAUDE.md for Claude Code integration",
        description="Create a CLAUDE.md in the project root so Claude Code picks up coding guidelines automatically",
    )
    claude_parser.add_argument(
        "output_dir",
        nargs="?",
        default=".",
        help="Project root directory (default: current directory)",
    )
    claude_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing CLAUDE.md",
    )
    claude_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    # Parse arguments
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Route to appropriate command handler
    try:
        if args.command == "setup":
            setup.run(args)
        elif args.command == "create":
            create.run(args)
        elif args.command == "claude":
            claude.run(args)
        elif args.command == "validate":
            validate.run(args)
        elif args.command == "dev":
            dev.run(args)
        else:
            parser.print_help()
            sys.exit(1)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose if hasattr(args, "verbose") else False:
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
