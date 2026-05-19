"""Unit tests for AIClientBase."""

from blueprint.agents.clients.ai.openai_client import OpenAIClient


class TestAIClientBaseInit:
    """AIClientBase is abstract; tested via OpenAIClient as the simplest concrete subclass."""

    def test_runtime_name_stored(self, mock_config) -> None:  # noqa: ARG002
        client = OpenAIClient("my_runtime")
        assert client._runtime_name == "my_runtime"

    def test_component_name_derived_from_runtime_name(self, mock_config) -> None:  # noqa: ARG002
        client = OpenAIClient("evaluator")
        assert client.name == "evaluator_ai_client"

    def test_model_initialises_as_none(self, mock_config) -> None:  # noqa: ARG002
        client = OpenAIClient("default")
        assert client._model is None

    def test_different_runtime_names_produce_different_component_names(self, mock_config) -> None:  # noqa: ARG002
        client_a = OpenAIClient("runtime_a")
        client_b = OpenAIClient("runtime_b")
        assert client_a.name != client_b.name
