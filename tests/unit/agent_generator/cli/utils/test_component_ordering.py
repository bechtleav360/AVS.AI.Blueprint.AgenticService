"""Tests for dependency-aware AppBuilder component registration ordering."""

from blueprint.agent_generator.cli.utils.naming_utils import (
    add_component_registration_to_main,
    extract_component_registrations,
    sort_components,
)


class TestExtractComponentRegistrations:
    """Test extract_component_registrations helper function."""

    def test_empty_app_builder(self):
        """Test extracting from empty AppBuilder."""
        content = "app = (\n    AppBuilder(config)\n    .build()\n)"
        components, app_idx, build_idx = extract_component_registrations(content)
        assert components == []
        assert app_idx == 1
        assert build_idx == 2

    def test_single_service(self):
        """Test extracting a single service."""
        content = "app = (\n    AppBuilder(config)\n    .with_service(MyService())\n    .build()\n)"
        components, app_idx, build_idx = extract_component_registrations(content)
        assert len(components) == 1
        assert components[0][0] == "service"
        assert "MyService" in components[0][1]

    def test_all_component_types(self):
        """Test extracting all component types."""
        content = (
            "app = (\n"
            "    AppBuilder(config)\n"
            "    .with_agent(my_agent)\n"
            "    .with_service(MyService())\n"
            "    .with_handler(MyHandler())\n"
            "    .with_rest_api(MyApi())\n"
            "    .with_scheduler(MyScheduler())\n"
            "    .build()\n"
            ")"
        )
        components, app_idx, build_idx = extract_component_registrations(content)
        assert len(components) == 5
        types = [c[0] for c in components]
        assert "agent" in types
        assert "service" in types
        assert "handler" in types
        assert "api" in types
        assert "scheduler" in types

    def test_with_cache(self):
        """Test extracting with cache component."""
        content = "app = (\n" "    AppBuilder(config)\n" "    .with_service(MyService())\n" "    .with_cache()\n" "    .build()\n" ")"
        components, _, _ = extract_component_registrations(content)
        assert len(components) == 2
        types = [c[0] for c in components]
        assert "service" in types
        assert "cache" in types


class TestSortComponents:
    """Test sort_components helper function."""

    def test_already_sorted(self):
        """Test sorting when already in correct order."""
        components = [
            ("service", ".with_service(MyService())"),
            ("agent", ".with_agent(my_agent)"),
            ("handler", ".with_handler(MyHandler())"),
            ("api", ".with_rest_api(MyApi())"),
            ("scheduler", ".with_scheduler(MyScheduler())"),
        ]
        sorted_comps = sort_components(components)
        types = [c[0] for c in sorted_comps]
        assert types == ["service", "agent", "handler", "api", "scheduler"]

    def test_reverse_order(self):
        """Test sorting when in reverse order."""
        components = [
            ("scheduler", ".with_scheduler(MyScheduler())"),
            ("api", ".with_rest_api(MyApi())"),
            ("handler", ".with_handler(MyHandler())"),
            ("agent", ".with_agent(my_agent)"),
            ("service", ".with_service(MyService())"),
        ]
        sorted_comps = sort_components(components)
        types = [c[0] for c in sorted_comps]
        assert types == ["service", "agent", "handler", "api", "scheduler"]

    def test_scrambled_order(self):
        """Test sorting when completely scrambled."""
        components = [
            ("handler", ".with_handler(Handler1())"),
            ("service", ".with_service(Service1())"),
            ("scheduler", ".with_scheduler(Scheduler1())"),
            ("agent", ".with_agent(agent1)"),
            ("api", ".with_rest_api(Api1())"),
        ]
        sorted_comps = sort_components(components)
        types = [c[0] for c in sorted_comps]
        assert types == ["service", "agent", "handler", "api", "scheduler"]

    def test_with_cache(self):
        """Test that cache always goes last."""
        components = [
            ("cache", ".with_cache()"),
            ("api", ".with_rest_api(MyApi())"),
            ("service", ".with_service(MyService())"),
        ]
        sorted_comps = sort_components(components)
        types = [c[0] for c in sorted_comps]
        assert types == ["service", "api", "cache"]

    def test_multiple_same_type(self):
        """Test sorting with multiple components of same type."""
        components = [
            ("handler", ".with_handler(Handler2())"),
            ("service", ".with_service(Service1())"),
            ("handler", ".with_handler(Handler1())"),
        ]
        sorted_comps = sort_components(components)
        types = [c[0] for c in sorted_comps]
        # Both handlers should come after service
        assert types[0] == "service"
        assert types[1:] == ["handler", "handler"]


class TestAddComponentRegistration:
    """Integration tests for add_component_registration_to_main - complete re-ordering."""

    def test_add_service_to_empty(self):
        """Test adding service to empty AppBuilder."""
        content = "app = (\n    AppBuilder(config)\n    .build()\n)"
        result = add_component_registration_to_main(content, "MyService", "service")
        assert ".with_service(MyService())" in result
        lines = result.split("\n")
        build_line = next(index for index, line in enumerate(lines) if ".build()" in line)
        service_line = next(index for index, line in enumerate(lines) if "with_service" in line)
        assert service_line < build_line

    def test_add_handler_reorders_before_api(self):
        """Test adding handler re-orders the entire chain before API."""
        content = "app = (\n" "    AppBuilder(config)\n" "    .with_rest_api(MyApi())\n" "    .build()\n" ")"
        result = add_component_registration_to_main(content, "MyHandler", "handler")
        assert ".with_handler(MyHandler())" in result
        lines = result.split("\n")
        handler_line = next(index for index, line in enumerate(lines) if "with_handler" in line)
        api_line = next(index for index, line in enumerate(lines) if "with_rest_api" in line)
        assert handler_line < api_line, "Handler should be re-ordered before API"

    def test_add_agent_reorders_entire_chain(self):
        """Test adding agent re-orders the entire chain correctly."""
        content = (
            "app = (\n" "    AppBuilder(config)\n" "    .with_handler(MyHandler())\n" "    .with_rest_api(MyApi())\n" "    .build()\n" ")"
        )
        result = add_component_registration_to_main(content, "MyAgent", "agent")
        assert ".with_agent(MyAgent)" in result
        lines = result.split("\n")
        agent_line = next(index for index, line in enumerate(lines) if "with_agent" in line)
        handler_line = next(index for index, line in enumerate(lines) if "with_handler" in line)
        api_line = next(index for index, line in enumerate(lines) if "with_rest_api" in line)
        # Agent should come before handler (not after)
        assert agent_line < handler_line < api_line

    def test_add_service_corrects_wrong_order(self):
        """Test adding service corrects wrong order in existing chain."""
        # Start with API, Handler, Agent (completely wrong order)
        content = (
            "app = (\n"
            "    AppBuilder(config)\n"
            "    .with_rest_api(MyApi())\n"
            "    .with_handler(MyHandler())\n"
            "    .with_agent(my_agent)\n"
            "    .build()\n"
            ")"
        )
        result = add_component_registration_to_main(content, "MyService", "service")

        # Verify correct order is restored: service, agent, handler, api
        lines = result.split("\n")
        service_line = next(index for index, line in enumerate(lines) if "with_service" in line)
        agent_line = next(index for index, line in enumerate(lines) if "with_agent" in line)
        handler_line = next(index for index, line in enumerate(lines) if "with_handler" in line)
        api_line = next(index for index, line in enumerate(lines) if "with_rest_api" in line)

        assert service_line < agent_line < handler_line < api_line, (
            f"Order not corrected: service={service_line}, agent={agent_line}, " f"handler={handler_line}, api={api_line}"
        )

    def test_out_of_order_creation_sequence_complete_reordering(self):
        """Test realistic scenario: components created in arbitrary order are completely re-ordered."""
        # Start with API
        content = "app = (\n    AppBuilder(config)\n    .with_rest_api(MyApi())\n    .build()\n)"

        # Add service (triggers re-order)
        content = add_component_registration_to_main(content, "MyService", "service")

        # Add handler (triggers re-order)
        content = add_component_registration_to_main(content, "MyHandler", "handler")

        # Add agent (triggers re-order)
        content = add_component_registration_to_main(content, "MyAgent", "agent")

        # Even though added in order: api, service, handler, agent
        # Should be re-ordered to: service, agent, handler, api
        lines = content.split("\n")
        service_line = next(index for index, line in enumerate(lines) if "with_service" in line)
        agent_line = next(index for index, line in enumerate(lines) if "with_agent" in line)
        handler_line = next(index for index, line in enumerate(lines) if "with_handler" in line)
        api_line = next(index for index, line in enumerate(lines) if "with_rest_api" in line)

        assert service_line < agent_line < handler_line < api_line, (
            f"Order not corrected: service={service_line}, agent={agent_line}, " f"handler={handler_line}, api={api_line}"
        )

    def test_agent_custom_instantiation_preserved(self):
        """Test that custom agent instantiation is preserved during re-ordering."""
        content = "app = (\n    AppBuilder(config)\n    .with_rest_api(MyApi())\n    .build()\n)"
        result = add_component_registration_to_main(content, "my_agent", "agent", instantiation="my_agent")
        assert ".with_agent(my_agent)" in result

    def test_multiple_handlers_preserved_and_reordered(self):
        """Test that multiple handlers are preserved and correctly positioned."""
        content = "app = (\n    AppBuilder(config)\n    .with_rest_api(MyApi())\n    .build()\n)"

        # Add first handler
        content = add_component_registration_to_main(content, "FirstHandler", "handler")

        # Add second handler
        content = add_component_registration_to_main(content, "SecondHandler", "handler")

        # Both should exist
        assert "with_handler(FirstHandler())" in content
        assert "with_handler(SecondHandler())" in content

        # Handlers should come before API
        lines = content.split("\n")
        handler_lines = [index for index, line in enumerate(lines) if "with_handler" in line]
        api_line = next(index for index, line in enumerate(lines) if "with_rest_api" in line)
        assert all(h < api_line for h in handler_lines)

    def test_cache_stays_last(self):
        """Test that cache component stays before .build()."""
        content = "app = (\n" "    AppBuilder(config)\n" "    .with_cache()\n" "    .with_rest_api(MyApi())\n" "    .build()\n" ")"
        result = add_component_registration_to_main(content, "MyService", "service")

        lines = result.split("\n")
        service_line = next(index for index, line in enumerate(lines) if "with_service" in line)
        cache_line = next(index for index, line in enumerate(lines) if "with_cache" in line)
        api_line = next(index for index, line in enumerate(lines) if "with_rest_api" in line)
        build_line = next(index for index, line in enumerate(lines) if ".build()" in line)

        # Correct order: service, api, cache, build
        assert service_line < api_line < cache_line < build_line