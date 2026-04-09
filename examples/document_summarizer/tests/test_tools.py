"""Unit tests for the text analysis tool functions."""

from src.tools.text_tools import extract_metadata, word_count


class TestWordCount:
    def test_simple_sentence(self) -> None:
        assert word_count("hello world") == 2

    def test_empty_string(self) -> None:
        assert word_count("") == 0

    def test_multiline(self) -> None:
        text = "first line\nsecond line\nthird line"
        assert word_count(text) == 6

    def test_extra_whitespace(self) -> None:
        assert word_count("  lots   of   space  ") == 3

    def test_single_word(self) -> None:
        assert word_count("hello") == 1


class TestExtractMetadata:
    def test_basic_text(self) -> None:
        text = "First sentence. Second sentence. Third sentence."
        meta = extract_metadata(text)
        assert meta["sentence_count"] == 3
        assert meta["paragraph_count"] == 1
        assert meta["has_urls"] is False
        assert meta["has_numbers"] is False
        assert isinstance(meta["avg_sentence_length"], float)

    def test_multiple_paragraphs(self) -> None:
        text = "Paragraph one sentence.\n\nParagraph two sentence."
        meta = extract_metadata(text)
        assert meta["paragraph_count"] == 2

    def test_contains_url(self) -> None:
        text = "Visit https://example.com for more info."
        meta = extract_metadata(text)
        assert meta["has_urls"] is True

    def test_contains_numbers(self) -> None:
        text = "There are 42 items remaining."
        meta = extract_metadata(text)
        assert meta["has_numbers"] is True

    def test_question_and_exclamation(self) -> None:
        text = "Is this a question? Yes it is! Great."
        meta = extract_metadata(text)
        assert meta["sentence_count"] == 3

    def test_avg_sentence_length(self) -> None:
        text = "One two. Three four five."
        meta = extract_metadata(text)
        # 5 words, 2 sentences -> 2.5
        assert meta["avg_sentence_length"] == 2.5
