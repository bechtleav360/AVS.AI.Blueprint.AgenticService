"""Data models for the trivia game."""

from .schemas import AnswerRequest, AnswerResult, GameQuestion, GameStartRequest

__all__ = ["GameStartRequest", "GameQuestion", "AnswerRequest", "AnswerResult"]
