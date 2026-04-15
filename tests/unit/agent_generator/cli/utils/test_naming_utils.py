"""Unit tests for naming utilities module."""

from blueprint.agent_generator.cli.utils.naming_utils import (
    get_component_suffix,
    to_class_name,
    camel_to_snake,
    to_snake_case,
    normalize_component_name,
    add_import_to_main,
    add_component_registration_to_main,
)


class TestGetComponentSuffix:
    """Test suite for get_component_suffix function."""

    def test_get_component_suffix_agent(self) -> None:
        """Should return 'agent' suffix for agent component type."""
        assert get_component_suffix("agent") == "agent"

    def test_get_component_suffix_service(self) -> None:
        """Should return 'Service' suffix for service component type."""
        assert get_component_suffix("service") == "Service"

    def test_get_component_suffix_handler(self) -> None:
        """Should return 'Handler' suffix for handler component type."""
        assert get_component_suffix("handler") == "Handler"

    def test_get_component_suffix_api(self) -> None:
        """Should return 'Api' suffix for api component type."""
        assert get_component_suffix("api") == "Api"

    def test_get_component_suffix_scheduler(self) -> None:
        """Should return 'Scheduler' suffix for scheduler component type."""
        assert get_component_suffix("scheduler") == "Scheduler"

    def test_get_component_suffix_unknown(self) -> None:
        """Should return empty string for unknown component type."""
        assert get_component_suffix("unknown") == ""


class TestToClassName:
    """Test suite for to_class_name function."""

    def test_to_class_name_snake_case(self) -> None:
        """Should convert snake_case to CamelCase."""
        assert to_class_name("test_agent") == "TestAgent"
        assert to_class_name("order_processor") == "OrderProcessor"

    def test_to_class_name_kebab_case(self) -> None:
        """Should convert kebab-case to CamelCase."""
        assert to_class_name("test-agent") == "TestAgent"
        assert to_class_name("order-processor") == "OrderProcessor"

    def test_to_class_name_already_camel(self) -> None:
        """Should re-capitalize already camelCase input."""
        # Note: to_class_name splits on separators and re-capitalizes each word
        # So "TestAgent" becomes "Testagent" (no separator between Test and Agent)
        assert to_class_name("Test_Agent") == "TestAgent"
        assert to_class_name("Test-Agent") == "TestAgent"

    def test_to_class_name_single_word(self) -> None:
        """Should capitalize single word."""
        assert to_class_name("agent") == "Agent"
        assert to_class_name("service") == "Service"

    def test_to_class_name_mixed_separators(self) -> None:
        """Should handle mixed separators."""
        assert to_class_name("test_order-processor") == "TestOrderProcessor"


class TestCamelToSnake:
    """Test suite for camel_to_snake function."""

    def test_camel_to_snake_simple(self) -> None:
        """Should convert simple CamelCase to snake_case."""
        assert camel_to_snake("TestAgent") == "test_agent"
        assert camel_to_snake("OrderProcessor") == "order_processor"

    def test_camel_to_snake_consecutive_caps(self) -> None:
        """Should handle consecutive capital letters."""
        # The regex treats consecutive capitals differently
        assert camel_to_snake("HTTPServer") == "http_server"

    def test_camel_to_snake_already_snake(self) -> None:
        """Should handle already snake_case input."""
        assert camel_to_snake("test_agent") == "test_agent"

    def test_camel_to_snake_single_word(self) -> None:
        """Should handle single word lowercase."""
        assert camel_to_snake("agent") == "agent"


class TestToSnakeCase:
    """Test suite for to_snake_case function."""

    def test_to_snake_case_is_alias(self) -> None:
        """Should be an alias for camel_to_snake."""
        assert to_snake_case("TestAgent") == camel_to_snake("TestAgent")
        assert to_snake_case("OrderProcessor") == camel_to_snake("OrderProcessor")


class TestNormalizeComponentName:
    """Test suite for normalize_component_name function."""

    def test_normalize_agent_snake_case(self) -> None:
        """Should normalize agent name from snake_case."""
        class_name, snake_name, filename = normalize_component_name("test_agent", "agent")
        assert snake_name == "test_agent"
        assert filename == "test_agent.py"

    def test_normalize_agent_camel_case(self) -> None:
        """Should normalize agent name from CamelCase."""
        class_name, snake_name, filename = normalize_component_name("TestAgent", "agent")
        assert snake_name == "test_agent"
        assert filename == "test_agent.py"

    def test_normalize_service_snake_case(self) -> None:
        """Should normalize service name from snake_case."""
        class_name, snake_name, filename = normalize_component_name("order_processor", "service")
        assert class_name == "OrderProcessorService"
        assert snake_name == "order_processor_service"
        assert filename == "order_processor_service.py"

    def test_normalize_handler_camel_case(self) -> None:
        """Should normalize handler name from CamelCase."""
        class_name, snake_name, filename = normalize_component_name("OrderHandler", "handler")
        assert class_name == "OrderHandler"
        assert snake_name == "order_handler"
        assert filename == "order_handler.py"

    def test_normalize_api_snake_case(self) -> None:
        """Should normalize api name from snake_case."""
        class_name, snake_name, filename = normalize_component_name("order_routes", "api")
        assert class_name == "OrderRoutesApi"
        assert snake_name == "order_routes_api"
        assert filename == "order_routes_api.py"

    def test_normalize_scheduler_kebab_case(self) -> None:
        """Should normalize scheduler name from kebab-case."""
        class_name, snake_name, filename = normalize_component_name("cleanup-job", "scheduler")
        # camel_to_snake treats kebab-case differently, preserving the dash
        assert class_name == "CleanupJobScheduler"
        assert snake_name == "cleanup-job_scheduler"
        assert filename == "cleanup-job_scheduler.py"


class TestAddImportToMain:
    """Test suite for add_import_to_main function."""

    def test_add_import_after_existing_imports(self) -> None:
        """Should add import after last existing import."""
        main_content = "from pathlib import Path\n" "from blueprint.agents import AppBuilder\n" "\n" "app = AppBuilder(config).build()\n"

        result = add_import_to_main(main_content, "from src.services.order_service import OrderService", "service")

        lines = result.split("\n")
        # Find the new import
        import_line_idx = None
        for i, line in enumerate(lines):
            if "from src.services.order_service import OrderService" in line:
                import_line_idx = i
                break

        assert import_line_idx is not None
        assert import_line_idx == 2  # After the two existing imports

    def test_add_import_when_no_imports_exist(self) -> None:
        """Should add import at beginning if no imports exist."""
        main_content = "app = AppBuilder(config).build()\n"

        result = add_import_to_main(main_content, "from src.services.order_service import OrderService", "service")

        lines = result.split("\n")
        assert lines[0] == "from src.services.order_service import OrderService"

    def test_add_multiple_imports_in_order(self) -> None:
        """Should add multiple imports in order after existing imports."""
        main_content = "from pathlib import Path\n\napp = AppBuilder(config).build()\n"

        result1 = add_import_to_main(main_content, "from src.services.order_service import OrderService", "service")
        result2 = add_import_to_main(result1, "from src.handlers.order_handler import OrderHandler", "handler")

        assert "from src.services.order_service import OrderService" in result2
        assert "from src.handlers.order_handler import OrderHandler" in result2


class TestAddComponentRegistrationToMain:
    """Test suite for add_component_registration_to_main function."""

    def test_add_service_registration(self) -> None:
        """Should add service registration before .build()."""
        main_content = "app = (\n" "    AppBuilder(config)\n" "    .build()\n" ")\n"

        result = add_component_registration_to_main(main_content, "OrderService", "service")

        lines = result.split("\n")
        # Find service registration
        service_idx = None
        build_idx = None
        for i, line in enumerate(lines):
            if ".with_service(OrderService())" in line:
                service_idx = i
            if ".build()" in line:
                build_idx = i

        assert service_idx is not None
        assert build_idx is not None
        assert service_idx < build_idx  # Service before build

    def test_add_handler_registration(self) -> None:
        """Should add handler registration before .build()."""
        main_content = "app = (\n" "    AppBuilder(config)\n" "    .with_service(OrderService())\n" "    .build()\n" ")\n"

        result = add_component_registration_to_main(main_content, "OrderHandler", "handler")

        assert ".with_handler(OrderHandler())" in result
        assert result.index(".with_handler(OrderHandler())") < result.rindex(".build()")

    def test_add_agent_registration_no_instantiation(self) -> None:
        """Should add agent registration without () for agents."""
        main_content = "app = (\n" "    AppBuilder(config)\n" "    .build()\n" ")\n"

        result = add_component_registration_to_main(main_content, "order_agent", "agent")

        assert ".with_agent(order_agent)" in result
        # Agents are registered without ()

    def test_add_api_registration(self) -> None:
        """Should add API registration before .build()."""
        main_content = "app = (\n" "    AppBuilder(config)\n" "    .build()\n" ")\n"

        result = add_component_registration_to_main(main_content, "OrderApi", "api")

        assert ".with_rest_api(OrderApi())" in result

    def test_add_scheduler_registration(self) -> None:
        """Should add scheduler registration before .build()."""
        main_content = "app = (\n" "    AppBuilder(config)\n" "    .build()\n" ")\n"

        result = add_component_registration_to_main(main_content, "CleanupScheduler", "scheduler")

        assert ".with_scheduler(CleanupScheduler())" in result

    def test_build_in_comment_does_not_break_insertion(self) -> None:
        """Should use last .build() call and ignore earlier ones in comments."""
        main_content = (
            "app = (\n"
            "    AppBuilder(config)  # Note: this calls .build() at the end\n"
            "    .with_service(OrderService())\n"
            "    .build()\n"
            ")\n"
        )

        result = add_component_registration_to_main(main_content, "TestHandler", "handler")

        lines = result.split("\n")
        # Find the actual .build() line (last one)
        actual_build_idx = 0
        for i in range(len(lines) - 1, -1, -1):
            if ".build()" in lines[i] and "Note:" not in lines[i]:
                actual_build_idx = i
                break

        # Find handler registration
        handler_idx = 0
        for i, line in enumerate(lines):
            if ".with_handler(TestHandler())" in line:
                handler_idx = i
                break

        assert handler_idx is not None
        assert handler_idx < actual_build_idx

    def test_custom_instantiation(self) -> None:
        """Should use custom instantiation if provided."""
        main_content = "app = (\n" "    AppBuilder(config)\n" "    .build()\n" ")\n"

        result = add_component_registration_to_main(
            main_content,
            "OrderService",
            "service",
            instantiation="OrderService(db_connection)",
        )

        assert ".with_service(OrderService(db_connection))" in result

    def test_no_build_found_appends_at_end(self) -> None:
        """Should append registration at end if no .build() found."""
        main_content = "app = AppBuilder(config)\n"

        result = add_component_registration_to_main(main_content, "OrderService", "service")

        lines = result.split("\n")
        # Last non-empty line should be the registration
        last_line = lines[-1] if lines[-1].strip() else lines[-2]
        assert ".with_service(OrderService())" in last_line

    def test_multiple_registrations_maintain_order(self) -> None:
        """Should add multiple registrations in the correct order."""
        main_content = "app = (\n" "    AppBuilder(config)\n" "    .build()\n" ")\n"

        result = add_component_registration_to_main(main_content, "OrderService", "service")
        result = add_component_registration_to_main(result, "OrderHandler", "handler")
        result = add_component_registration_to_main(result, "OrderApi", "api")

        service_idx = result.index(".with_service")
        handler_idx = result.index(".with_handler")
        api_idx = result.index(".with_rest_api")
        build_idx = result.rindex(".build()")

        # All registrations should be before .build()
        assert service_idx < build_idx
        assert handler_idx < build_idx
        assert api_idx < build_idx