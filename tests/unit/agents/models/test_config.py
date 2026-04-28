"""Unit tests for EventPublishingConfig and its parsing helpers."""

import pytest
from pydantic import ValidationError

from blueprint.agents.models.config import EventPublishingConfig, TopicConfig

# ---------------------------------------------------------------------------
# normalize_topic_mapping — value types
# ---------------------------------------------------------------------------


class TestNormalizeTopicMappingValueTypes:
    def test_topic_config_value_passed_through(self) -> None:
        tc = TopicConfig(topic="t", routing_key="rk")
        cfg = EventPublishingConfig(topic_mapping={"e": tc})
        assert cfg.topic_mapping["e"] is tc

    def test_dict_value_converted_to_topic_config(self) -> None:
        cfg = EventPublishingConfig(topic_mapping={"e": {"topic": "t", "routing_key": "rk"}})
        assert isinstance(cfg.topic_mapping["e"], TopicConfig)
        assert cfg.topic_mapping["e"].routing_key == "rk"

    def test_plain_string_value_converted_to_topic_config(self) -> None:
        cfg = EventPublishingConfig(topic_mapping={"e": "my-topic"})
        assert cfg.topic_mapping["e"].topic == "my-topic"
        assert cfg.topic_mapping["e"].routing_key is None

    def test_invalid_value_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            EventPublishingConfig(topic_mapping={"e": 42})

    def test_non_dict_mapping_raises(self) -> None:
        with pytest.raises(ValidationError):
            EventPublishingConfig(topic_mapping="not-a-dict")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _parse_mapping_string — via string topic_mapping
# ---------------------------------------------------------------------------


class TestParseMappingString:
    def test_empty_string_returns_empty_mapping(self) -> None:
        cfg = EventPublishingConfig(topic_mapping="")
        assert cfg.topic_mapping == {}

    def test_whitespace_only_returns_empty_mapping(self) -> None:
        cfg = EventPublishingConfig(topic_mapping="   ")
        assert cfg.topic_mapping == {}

    def test_quoted_key_dict_string(self) -> None:
        cfg = EventPublishingConfig(topic_mapping='{"my.event": "my-topic"}')
        assert cfg.topic_mapping["my.event"].topic == "my-topic"

    def test_unquoted_key_dict_string_auto_quoted(self) -> None:
        """Keys without quotes (as produced by some env-var serialisers) are fixed up."""
        cfg = EventPublishingConfig(topic_mapping="{my.event: 'my-topic'}")
        assert cfg.topic_mapping["my.event"].topic == "my-topic"

    def test_multiple_entries_parsed(self) -> None:
        cfg = EventPublishingConfig(topic_mapping='{"a.event": "topic-a", "b.event": "topic-b"}')
        assert "a.event" in cfg.topic_mapping
        assert "b.event" in cfg.topic_mapping

    def test_non_brace_string_raises(self) -> None:
        with pytest.raises(ValidationError, match="Unsupported topic mapping format"):
            EventPublishingConfig(topic_mapping="my.event=my-topic")

    def test_malformed_brace_string_raises(self) -> None:
        with pytest.raises(ValidationError, match="Invalid topic mapping string"):
            EventPublishingConfig(topic_mapping="{unclosed: }")


# ---------------------------------------------------------------------------
# _parse_topic_config_value — via string values inside a dict mapping
# ---------------------------------------------------------------------------


class TestParseTopicConfigValue:
    def test_plain_string_becomes_topic(self) -> None:
        cfg = EventPublishingConfig(topic_mapping={"e": "plain-topic"})
        assert cfg.topic_mapping["e"].topic == "plain-topic"

    def test_plain_string_has_no_routing_key(self) -> None:
        cfg = EventPublishingConfig(topic_mapping={"e": "plain-topic"})
        assert cfg.topic_mapping["e"].routing_key is None

    def test_map_format_with_topic_only(self) -> None:
        cfg = EventPublishingConfig(topic_mapping={"e": "map[topic:my-topic]"})
        assert cfg.topic_mapping["e"].topic == "my-topic"

    def test_map_format_with_topic_and_routing_key(self) -> None:
        cfg = EventPublishingConfig(topic_mapping={"e": "map[topic:my-topic routing_key:my-rk]"})
        assert cfg.topic_mapping["e"].topic == "my-topic"
        assert cfg.topic_mapping["e"].routing_key == "my-rk"

    def test_empty_map_raises(self) -> None:
        with pytest.raises(ValidationError, match="Empty map\\[\\]"):
            EventPublishingConfig(topic_mapping={"e": "map[]"})

    def test_map_without_topic_entry_raises(self) -> None:
        with pytest.raises(ValidationError, match="must include a 'topic' entry"):
            EventPublishingConfig(topic_mapping={"e": "map[routing_key:rk]"})

    def test_map_with_invalid_entry_raises(self) -> None:
        with pytest.raises(ValidationError, match="Invalid map\\[\\] entry"):
            EventPublishingConfig(topic_mapping={"e": "map[no-colon-here]"})
