"""Tool functions for document text analysis.

Each function is registered as a Pydantic AI tool. Docstrings serve as the
tool descriptions that the LLM sees.
"""

import re
from typing import Any


def word_count(text: str) -> int:
    """Count the total number of words in the given text.

    Args:
        text: The document text to count words in.

    Returns:
        The number of words in the text.
    """
    return len(text.split())


def extract_metadata(text: str) -> dict[str, Any]:
    """Extract structural metadata from the given text.

    Returns sentence count, paragraph count, average sentence length,
    whether the text contains URLs, and whether it contains numbers.

    Args:
        text: The document text to analyse.

    Returns:
        A dictionary with keys: sentence_count, paragraph_count,
        avg_sentence_length, has_urls, has_numbers.
    """
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    sentence_count = len(sentences)

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    paragraph_count = max(len(paragraphs), 1)

    total_words = len(text.split())
    avg_sentence_length = round(total_words / sentence_count, 1) if sentence_count > 0 else 0.0

    has_urls = bool(re.search(r"https?://\S+", text))
    has_numbers = bool(re.search(r"\d+", text))

    return {
        "sentence_count": sentence_count,
        "paragraph_count": paragraph_count,
        "avg_sentence_length": avg_sentence_length,
        "has_urls": has_urls,
        "has_numbers": has_numbers,
    }
