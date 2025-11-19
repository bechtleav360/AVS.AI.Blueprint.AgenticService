"""REST API for the trivia game."""

import logging
from typing import Any

from blueprint.agents.api.rest import RestApi
from fastapi import HTTPException

from ..models import AnswerRequest, AnswerResult, GameQuestion, GameStartRequest
from ..services import TriviaService

logger = logging.getLogger(__name__)


class TriviaGameRestApi(RestApi):
    """REST API for trivia game operations."""

    def __init__(self) -> None:
        """Initialize the trivia game REST API.

        The component registry and agent will be wired in by AppBuilder.
        """
        self._component_registry: Any = None
        self._agent: Any = None
        self.trivia_service: Any = None
        self.router = None
        self.payload_type = GameStartRequest

    def with_agent(self, agent: Any) -> "TriviaGameRestApi":
        """Register an agent with this REST API.

        Args:
            agent: The agent instance to use (with prompts attached)

        Returns:
            Self for chaining
        """
        self._agent = agent
        # Initialize the service with the agent
        # Prompts are retrieved from agent.prompts by the service
        self.trivia_service = TriviaService(agent=agent)
        return self

    def _register_routes(self) -> None:
        """Register trivia game routes."""

        @self.router.post("/game/start", response_model=dict)
        async def start_game(request: GameStartRequest) -> dict:
            """Start a new trivia game.

            Args:
                request: Game start parameters

            Returns:
                Game session ID
            """
            try:
                game_id = self.trivia_service.start_game(
                    difficulty=request.difficulty,
                    num_questions=request.num_questions,
                )
                return {"game_id": game_id, "status": "started"}
            except Exception as e:
                logger.error(f"Error starting game: {e}")
                raise HTTPException(status_code=400, detail=str(e))

        @self.router.get("/game/{game_id}/question", response_model=GameQuestion)
        async def get_question(game_id: str) -> GameQuestion:
            """Get the next trivia question.

            Args:
                game_id: Game session ID

            Returns:
                Trivia question
            """
            try:
                question = await self.trivia_service.get_next_question(game_id)
                return GameQuestion(**question)
            except ValueError as e:
                logger.error(f"Error getting question: {e}")
                raise HTTPException(status_code=404, detail=str(e))
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                raise HTTPException(status_code=500, detail="Internal server error")

        @self.router.post("/game/answer", response_model=AnswerResult)
        async def submit_answer(request: AnswerRequest) -> AnswerResult:
            """Submit an answer to a trivia question.

            Args:
                request: Answer submission

            Returns:
                Answer evaluation result
            """
            try:
                result = await self.trivia_service.evaluate_answer(
                    request.game_id,
                    request.question_id,
                    request.answer,
                )
                return AnswerResult(**result)
            except ValueError as e:
                logger.error(f"Error evaluating answer: {e}")
                raise HTTPException(status_code=404, detail=str(e))
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                raise HTTPException(status_code=500, detail="Internal server error")

        @self.router.get("/game/{game_id}/score", response_model=dict)
        async def get_score(game_id: str) -> dict:
            """Get the current game score.

            Args:
                game_id: Game session ID

            Returns:
                Score information
            """
            try:
                score = self.trivia_service.get_score(game_id)
                return score
            except ValueError as e:
                logger.error(f"Error getting score: {e}")
                raise HTTPException(status_code=404, detail=str(e))
