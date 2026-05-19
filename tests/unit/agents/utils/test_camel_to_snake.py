"""Unit tests for camel_to_snake."""

from blueprint.agents.utils import camel_to_snake


class TestCamelToSnake:
    # ------------------------------------------------------------------
    # Standard CamelCase
    # ------------------------------------------------------------------

    def test_two_word_class(self) -> None:
        assert camel_to_snake("MyComponent") == "my_component"

    def test_three_word_class(self) -> None:
        assert camel_to_snake("SimpleBaseClass") == "simple_base_class"

    def test_single_word_lowercase(self) -> None:
        assert camel_to_snake("Simple") == "simple"

    # ------------------------------------------------------------------
    # Acronyms
    # ------------------------------------------------------------------

    def test_leading_acronym(self) -> None:
        assert camel_to_snake("AIConfig") == "ai_config"

    def test_acronym_mid_string(self) -> None:
        assert camel_to_snake("parseHTTPResponse") == "parse_http_response"

    def test_full_acronym_prefix(self) -> None:
        assert camel_to_snake("HTTPSRequest") == "https_request"

    def test_trailing_acronym(self) -> None:
        assert camel_to_snake("MyAPI") == "my_api"

    def test_acronym_before_word(self) -> None:
        assert camel_to_snake("ConfigJSON") == "config_json"

    # ------------------------------------------------------------------
    # Numbers
    # ------------------------------------------------------------------

    def test_number_in_name(self) -> None:
        assert camel_to_snake("Base64Encoder") == "base64_encoder"

    def test_number_followed_by_uppercase(self) -> None:
        assert camel_to_snake("Version2Config") == "version2_config"

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_empty_string(self) -> None:
        assert camel_to_snake("") == ""

    def test_single_uppercase_char(self) -> None:
        assert camel_to_snake("A") == "a"

    def test_already_snake_case_unchanged(self) -> None:
        assert camel_to_snake("already_snake") == "already_snake"

    def test_all_uppercase_acronym(self) -> None:
        assert camel_to_snake("HTTP") == "http"
