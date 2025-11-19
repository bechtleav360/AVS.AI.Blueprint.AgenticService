# Trivia Game Example

A RESTful trivia game API that uses an LLM agent to generate questions and evaluate answers. Demonstrates using the Blueprint Agents framework for REST-based AI applications without event handlers.

## Features

- ✅ **LLM-Powered** - Uses Pydantic AI for intelligent question generation and answer evaluation
- ✅ **RESTful API** - Clean HTTP endpoints for game interaction
- ✅ **No Handlers** - Pure REST-based, no event-driven architecture
- ✅ **Session Management** - Tracks game state and score
- ✅ **Type-Safe** - Pydantic models for all requests/responses
- ✅ **Production-Ready** - Health checks and proper logging

## Prerequisites

1. **Install the Blueprint Agents Framework**:

   ```bash
   pip install avs-blueprint-agents>=0.1.17
   ```

   Or install from the root repository in development mode:

   ```bash
   cd /path/to/Agents_Blueprint
   pip install -e .
   ```

2. **Python 3.13+**

3. **LLM API Key** (OpenAI or other provider)

## Getting Started

### 1. Install Dependencies

```bash
pip install -e .
```

### 2. Configure LLM

Set your LLM API key:

```bash
export OPENAI_API_KEY="sk-..."
```

Or add to `secrets.toml`:

```toml
[default]
openai_api_key = "sk-..."
```

### 3. Run the Service

```bash
python -m uvicorn src.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`.

### 4. Access the API

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health/live

## API Endpoints

### Start Game

```bash
curl -X POST http://localhost:8000/api/game/start \
  -H "Content-Type: application/json" \
  -d '{"difficulty": "medium", "num_questions": 5}'
```

**Response:**
```json
{
  "game_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "started"
}
```

### Get Question

```bash
curl http://localhost:8000/api/game/{game_id}/question
```

**Response:**
```json
{
  "question_id": 0,
  "question": "Question 1: What is the capital of France?",
  "category": "Geography",
  "difficulty": "medium"
}
```

### Submit Answer

```bash
curl -X POST http://localhost:8000/api/game/answer \
  -H "Content-Type: application/json" \
  -d '{
    "game_id": "550e8400-e29b-41d4-a716-446655440000",
    "question_id": 0,
    "answer": "Paris"
  }'
```

**Response:**
```json
{
  "game_id": "550e8400-e29b-41d4-a716-446655440000",
  "question_id": 0,
  "is_correct": true,
  "explanation": "Correct! Paris is the capital of France.",
  "current_score": 1,
  "total_questions": 5
}
```

### Get Score

```bash
curl http://localhost:8000/api/game/{game_id}/score
```

**Response:**
```json
{
  "game_id": "550e8400-e29b-41d4-a716-446655440000",
  "score": 3,
  "total_questions": 5,
  "current_question": 3,
  "percentage": 60
}
```

## Project Structure

```
trivia_game/
├── src/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entry point
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py           # Game API routes
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py          # Request/response schemas
│   └── services/
│       ├── __init__.py
│       └── trivia_service.py   # Game logic with LLM
├── tests/
│   ├── __init__.py
│   └── test_routes.py          # Route tests
├── settings.toml               # Configuration
├── secrets.toml.example        # Secrets template
├── pyproject.toml              # Dependencies
└── README.md                   # This file
```

## Running Tests

```bash
pytest tests/ -v
```

## Configuration

Edit `settings.toml` to customize:
- App name and version
- Server host and port
- Game difficulty and number of questions
- Logging level

## How It Works

1. **Game Start**: Player initiates a new game with difficulty level
2. **Question Generation**: LLM generates a trivia question
3. **Answer Submission**: Player submits their answer
4. **Answer Evaluation**: LLM evaluates the answer and provides explanation
5. **Score Tracking**: Game tracks correct answers and calculates score

## LLM Integration

The example uses Pydantic AI with OpenAI's GPT-4o-mini model by default. You can customize:

- **Model**: Change in `trivia_service.py` line 26
- **System Prompt**: Modify the system prompt to change question style
- **Provider**: Use any provider supported by Pydantic AI

## Extending the Example

To enhance the game:

1. **Add Difficulty Levels**: Adjust LLM prompts based on difficulty
2. **Add Categories**: Allow players to choose question categories
3. **Add Leaderboard**: Store high scores in a database
4. **Add Multiplayer**: Support multiple players in one game
5. **Add Persistence**: Save games to a database

## Troubleshooting

### Port already in use

```bash
python -m uvicorn src.main:app --port 8001
```

### LLM API errors

Ensure your API key is set and valid:

```bash
echo $OPENAI_API_KEY
```

### Module not found errors

Ensure the framework is installed:

```bash
pip install -e .
```

## License

MIT License - See LICENSE file for details

## Support

For issues or questions about the framework, see the main [Blueprint Agents documentation](../../README.md).
