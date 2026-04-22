"""Unit tests for MetricsExtractor."""

import types

from blueprint.agents.agent.metrics import MetricsExtractor

# ---------------------------------------------------------------------------
# extract_response_text
# ---------------------------------------------------------------------------


class TestExtractResponseText:
    def test_returns_data_when_present(self) -> None:
        result = types.SimpleNamespace(data="response text")
        assert MetricsExtractor.extract_response_text(result) == "response text"

    def test_returns_output_when_no_data_attribute(self) -> None:
        result = types.SimpleNamespace(output="output text")
        assert MetricsExtractor.extract_response_text(result) == "output text"

    def test_falls_back_to_str_when_neither_attribute(self) -> None:
        result = types.SimpleNamespace()
        assert MetricsExtractor.extract_response_text(result) == str(result)


# ---------------------------------------------------------------------------
# extract_usage_info
# ---------------------------------------------------------------------------


class TestExtractUsageInfo:
    def test_returns_all_fields_when_present(self) -> None:
        usage = types.SimpleNamespace(
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
            requests=1,
        )
        result = types.SimpleNamespace(usage=lambda: usage)

        info = MetricsExtractor.extract_usage_info(result)

        assert info == {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30, "requests": 1}

    def test_includes_only_present_attributes(self) -> None:
        usage = types.SimpleNamespace(input_tokens=5, output_tokens=3)
        result = types.SimpleNamespace(usage=lambda: usage)

        info = MetricsExtractor.extract_usage_info(result)

        assert info == {"input_tokens": 5, "output_tokens": 3}

    def test_returns_empty_dict_when_usage_returns_none(self) -> None:
        result = types.SimpleNamespace(usage=lambda: None)
        assert MetricsExtractor.extract_usage_info(result) == {}

    def test_returns_empty_dict_when_usage_raises(self) -> None:
        def broken() -> None:
            raise RuntimeError("unavailable")

        result = types.SimpleNamespace(usage=broken)
        assert MetricsExtractor.extract_usage_info(result) == {}

    def test_returns_empty_dict_when_no_usage_attribute(self) -> None:
        result = types.SimpleNamespace()
        assert MetricsExtractor.extract_usage_info(result) == {}

    def test_returns_empty_dict_when_usage_is_not_callable(self) -> None:
        result = types.SimpleNamespace(usage="not-callable")
        assert MetricsExtractor.extract_usage_info(result) == {}
