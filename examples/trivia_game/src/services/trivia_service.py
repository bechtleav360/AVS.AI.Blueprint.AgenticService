"""Trivia game service with LLM integration."""

import json
import logging
import uuid
from typing import Any

from blueprint.agents.agent import AgentBuilder
from pydantic_ai import Agent, AgentRunResult

from blueprint.agents.base import BusinessService

logger: logging.Logger = logging.getLogger(__name__)


class TriviaService(BusinessService):
    """Service for managing trivia games with LLM-powered questions and evaluation."""

    games: dict[str, dict[str, Any]]
    agent: Agent

    def __init__(self) -> None:
        """Initialize the trivia service."""
        super().__init__("trivia_service")

        self.games: dict[str, dict[str, Any]] = {}

    def start_game(self, difficulty: str = "medium", num_questions: int = 5) -> str:
        """Start a new trivia game.

        Args:
            difficulty: Game difficulty level
            num_questions: Number of questions

        Returns:
            Game session ID
        """
        game_id = str(uuid.uuid4())
        self.games[game_id] = {
            "difficulty": difficulty,
            "num_questions": num_questions,
            "current_question": 0,
            "score": 0,
            "questions": [],
        }
        logger.info(f"Started game {game_id} with difficulty {difficulty}")
        return game_id

    async def get_next_question(self, game_id: str) -> dict[str, Any]:
        """Get the next trivia question.

        Args:
            game_id: Game session ID

        Returns:
            Question data with id, question, category, difficulty
        """
        if game_id not in self.games:
            raise ValueError(f"Game {game_id} not found")

        game = self.games[game_id]
        question_num = game["current_question"]

        if question_num >= game["num_questions"]:
            raise ValueError(f"Game {game_id} is complete")

        # Generate question using LLM agent
        prompt = self.get_registry().get_agent("trivia_master").get_prompt("generate_question").format(difficulty=game["difficulty"])
        try:
            result: AgentRunResult = await self.get_registry().get_agent("trivia_master").run(prompt)

            logger.info("Result object type: %s", type(result).__name__)
            # Extract response text using framework utility
            response_text = AgentBuilder.extract_response_text(result)
            # Log usage information
            usage = AgentBuilder.extract_usage_info(result)
            logger.info("Extracted usage info: %s", usage)
            if usage:
                logger.info("Question generation - Tokens: input=%s, output=%s", usage.get("input_tokens"), usage.get("output_tokens"))
            else:
                logger.info("No usage information extracted")
            # Parse JSON response from LLM
            try:
                llm_response = json.loads(response_text)
                question_data = {
                    "question_id": question_num,
                    "question": f"Question {question_num + 1}: {llm_response.get('question', 'Unknown question')}",
                    "category": llm_response.get("category", "General Knowledge"),
                    "difficulty": llm_response.get("difficulty", game["difficulty"]),
                    "correct_answer": llm_response.get("correct_answer", ""),
                }
            except (json.JSONDecodeError, KeyError) as parse_error:
                logger.warning("Failed to parse LLM response as JSON: %s. Response: %s", parse_error, response_text)
                # Fallback if JSON parsing fails
                question_data = {
                    "question_id": question_num,
                    "question": f"Question {question_num + 1}: {response_text}",
                    "category": "General Knowledge",
                    "difficulty": game["difficulty"],
                    "correct_answer": "",
                }
            game["questions"].append(question_data)
            return question_data
        except Exception as e:
            logger.error(f"Error generating question: {e}")
            # Fallback question
            return {
                "question_id": question_num,
                "question": f"Question {question_num + 1}: What is the capital of France?",
                "category": "Geography",
                "difficulty": game["difficulty"],
                "correct_answer": "Paris",
            }

    async def evaluate_answer(self, game_id: str, question_id: int, answer: str) -> dict[str, Any]:
        """Evaluate a player's answer.

        Args:
            game_id: Game session ID
            question_id: Question ID
            answer: Player's answer

        Returns:
            Evaluation result with correctness and explanation
        """
        if game_id not in self.games:
            raise ValueError(f"Game {game_id} not found")

        game = self.games[game_id]

        if question_id >= len(game["questions"]):
            raise ValueError(f"Question {question_id} not found")

        question = game["questions"][question_id]

        # Use LLM to evaluate answer
        prompt = (
            self.get_registry()
            .get_agent("trivia_master")
            .get_prompt("evaluate_answer")
            .format(
                question=question["question"],
                correct_answer=question.get("correct_answer", "Unknown"),
                player_answer=answer,
            )
        )
        try:
            result = await self.get_registry().get_agent("trivia_master").run(prompt)
            # Extract response text using framework utility
            response_text = AgentBuilder.extract_response_text(result)
            # Log usage information
            usage = AgentBuilder.extract_usage_info(result)
            if usage:
                logger.info("Answer evaluation - Tokens: input=%s, output=%s", usage.get("input_tokens"), usage.get("output_tokens"))

            # Try to parse JSON response from LLM
            is_correct = False
            explanation = response_text
            try:
                llm_response = json.loads(response_text)
                is_correct = llm_response.get("is_correct", False)
                explanation = llm_response.get("explanation", response_text)
            except (json.JSONDecodeError, KeyError):
                # Fallback: check if "correct" is in response
                is_correct = "correct" in response_text.lower()

            if is_correct:
                game["score"] += 1

            game["current_question"] += 1

            return {
                "game_id": game_id,
                "question_id": question_id,
                "is_correct": is_correct,
                "explanation": explanation,
                "current_score": game["score"],
                "total_questions": game["num_questions"],
            }
        except Exception as e:
            logger.error(f"Error evaluating answer: {e}")
            # Fallback evaluation
            return {
                "game_id": game_id,
                "question_id": question_id,
                "is_correct": False,
                "explanation": "Could not evaluate answer",
                "current_score": game["score"],
                "total_questions": game["num_questions"],
            }

    def get_score(self, game_id: str) -> dict[str, Any]:
        """Get the current game score.

        Args:
            game_id: Game session ID

        Returns:
            Score information
        """
        if game_id not in self.games:
            raise ValueError(f"Game {game_id} not found")

        game = self.games[game_id]
        return {
            "game_id": game_id,
            "score": game["score"],
            "total_questions": game["num_questions"],
            "current_question": game["current_question"],
            "percentage": int((game["score"] / game["num_questions"]) * 100) if game["num_questions"] > 0 else 0,
        }
