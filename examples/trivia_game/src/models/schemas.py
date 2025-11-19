"""Request and response schemas for the trivia game."""

from pydantic import BaseModel, Field


class GameStartRequest(BaseModel):
    """Request to start a new game."""

    difficulty: str = Field(default="medium", description="Difficulty level: easy, medium, hard")
    num_questions: int = Field(default=5, description="Number of questions in the game")


class GameQuestion(BaseModel):
    """A trivia question."""

    question_id: int = Field(..., description="Unique question identifier")
    question: str = Field(..., description="The trivia question")
    category: str = Field(..., description="Question category")
    difficulty: str = Field(..., description="Question difficulty")


class AnswerRequest(BaseModel):
    """Request to submit an answer."""

    game_id: str = Field(..., description="Game session ID")
    question_id: int = Field(..., description="Question ID")
    answer: str = Field(..., description="Player's answer")


class AnswerResult(BaseModel):
    """Result of answer evaluation."""

    game_id: str = Field(..., description="Game session ID")
    question_id: int = Field(..., description="Question ID")
    is_correct: bool = Field(..., description="Whether the answer was correct")
    explanation: str = Field(..., description="Explanation of the answer")
    current_score: int = Field(..., description="Current game score")
    total_questions: int = Field(..., description="Total questions in game")
