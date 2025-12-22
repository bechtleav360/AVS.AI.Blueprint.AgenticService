# Customer Support Q&A Collaboration Example

A RESTful API demonstrating two-agent collaboration in a senior-junior support relationship. The junior agent generates detailed, comprehensive answers to customer questions (many tokens), and the senior agent quickly validates the answer (few tokens). This example showcases efficient agent-to-agent interaction using the Blueprint Agents framework with vLLM models.

## Features

- ✅ **Two-Agent Collaboration** - Junior generates content, senior validates
- ✅ **Optimal Token Usage** - Junior produces many tokens (detailed answers), senior produces few tokens (quick validation)
- ✅ **vLLM Integration** - Uses fast (7B) and complex (32B) models for different roles
- ✅ **RESTful API** - Easy to test with simple HTTP requests
- ✅ **Realistic Use Case** - Customer support Q&A with quality control
- ✅ **Type-Safe** - Pydantic models for all requests/responses
- ✅ **Production-Ready** - Health checks, logging, and proper error handling

## Use Case

This example simulates a customer support Q&A workflow with quality control:
1. **Junior Support Agent** (fast 7B model) receives a customer question and generates a detailed, comprehensive answer (200-500 words, many tokens)
2. **Senior Support Supervisor** (complex 32B model) quickly validates the answer for accuracy and appropriateness (1-2 sentences, few tokens)
3. The system returns both the answer and validation in a single API call

**Why this design?**
- Junior agent does the heavy lifting (content generation) with a fast model
- Senior agent does quick validation with a more capable model
- Matches real-world token usage patterns: generation requires many tokens, validation requires few
- Easy to test via REST API - just send a question!

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

3. **vLLM Instance** - Access to a vLLM server (configured in `settings.toml`)

## Getting Started

### 1. Install Dependencies

```bash
pip install -e .
```

### 2. Configure vLLM

The example is pre-configured to use vLLM models:
- **Junior Support Agent**: `Qwen/Qwen2.5-7B-Instruct` (fast, smaller model, max_tokens=2000)
- **Senior Support Supervisor**: `Qwen/Qwen2.5-32B-Instruct` (slower, more capable model, max_tokens=200)

Note the different `max_tokens` settings - junior generates long answers, senior provides brief validation.

Edit `settings.toml` to customize the vLLM endpoint or models:

```toml
[default.runtimes.junior_support]
model_provider = "vllm"
model_base_url = "https://your-vllm-instance.com/v1"
model_name = "Qwen/Qwen2.5-7B-Instruct"
model_max_tokens = 2000
model_temperature = 0.7

[default.runtimes.senior_support]
model_provider = "vllm"
model_base_url = "https://your-vllm-instance.com/v1"
model_name = "Qwen/Qwen2.5-32B-Instruct"
model_max_tokens = 200
model_temperature = 0.2
```

If your vLLM instance requires authentication, create `secrets.toml`:

```toml
[default]
vllm_api_key = "your-api-key-here"
```

### 3. Run the Service

```bash
python -m uvicorn src.main:app --reload --port 8001
```

Or use VS Code debugger (see `.vscode/launch.json`).

The API will be available at `http://localhost:8001`.

### 4. Access the API

- **Swagger UI**: http://localhost:8001/docs
- **ReDoc**: http://localhost:8001/redoc
- **Health Check**: http://localhost:8001/health/live

## API Endpoints

### Ask a Question

Submit a customer support question and get an answer with validation:

```bash
curl -X POST http://localhost:8001/api/support/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "How do I reset my password?",
    "category": "technical",
    "context": "User forgot password and cannot access email"
  }'
```

**Response:**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "question": "How do I reset my password?",
  "answer": "To reset your password, follow these steps:\n\n1. Go to the login page and click 'Forgot Password'\n2. Enter your email address or username\n3. Check your email for a password reset link (it may take a few minutes)\n4. Click the link in the email\n5. Create a new strong password...\n\nIf you don't have access to your email, you can contact our support team at support@example.com or call 1-800-SUPPORT. They can verify your identity and help you regain access to your account. Make sure to have your account information ready...",
  "confidence": 0.9,
  "sources": ["KB-1234: Password Reset Guide", "KB-5678: Account Recovery"],
  "validated": true,
  "validation_reason": "Answer is accurate and comprehensive. Covers both standard and alternative recovery methods.",
  "status": "approved"
}
```

### Get Session Details

```bash
curl http://localhost:8001/api/support/{session_id}
```

### List All Sessions

```bash
curl http://localhost:8001/api/support/sessions/list
```

## Project Structure

```
customer_support_qa/
├── src/
│   ├── __init__.py
│   ├── main.py                      # FastAPI app with both agents
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py                # REST API routes
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py               # Request/response schemas
│   ├── services/
│   │   ├── __init__.py
│   │   └── code_review_service.py   # Two-agent collaboration logic
│   └── prompts/
│       ├── junior_system.prompt     # Junior support agent system prompt
│       ├── senior_system.prompt     # Senior supervisor system prompt
│       ├── answer_question.prompt   # Question answering prompt
│       └── validate_answer.prompt   # Answer validation prompt
├── tests/
│   ├── __init__.py
│   ├── test_routes.py               # API tests
│   ├── test_service.py              # Service tests
│   └── test_integration.py          # Integration tests
├── settings.toml                    # Configuration
├── secrets.toml.example             # Secrets template
├── pyproject.toml                   # Dependencies
└── README.md                        # This file
```

## Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run unit tests only
pytest tests/test_service.py -v

# Run integration tests
pytest tests/test_integration.py -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html
```

## Configuration

Edit `settings.toml` to customize:
- **Models**: Change the vLLM models for each agent
- **Temperature**: Adjust creativity (junior: 0.7, senior: 0.2)
- **Max Tokens**: Control response length (junior: 2000, senior: 200)
- **Server**: Host and port settings
- **Logging**: Debug level and format

## How It Works

### Agent Roles

**Junior Support Agent (7B Model)**:
- Fast and efficient for content generation
- Generates detailed, comprehensive answers (200-500 words)
- Produces **many tokens** (typically 300-800 output tokens)
- Includes examples, step-by-step instructions, and context
- Temperature: 0.7 (more creative and conversational)
- Max tokens: 2000

**Senior Support Supervisor (32B Model)**:
- More capable model for quality validation
- Quickly validates answer accuracy and appropriateness
- Produces **few tokens** (typically 20-50 output tokens)
- Brief, concise feedback (1-2 sentences)
- Temperature: 0.2 (more focused and consistent)
- Max tokens: 200

### Workflow

1. **Request Received**: API receives customer question
2. **Junior Generates**: Junior agent creates detailed answer (MANY tokens)
3. **Senior Validates**: Senior agent validates answer (FEW tokens)
4. **Response Returned**: Both answer and validation sent back together

### Token Usage Pattern

This design matches the requested pattern:
- **Junior (fast model)**: Consumes and produces MANY tokens
  - Input: ~100-200 tokens (question + context)
  - Output: ~300-800 tokens (detailed answer)
- **Senior (slow model)**: Produces FEW tokens
  - Input: ~400-1000 tokens (question + junior's answer)
  - Output: ~20-50 tokens (brief validation)

### Agent Interaction

The agents work in sequence:
1. Junior agent receives the question and generates a comprehensive answer
2. Senior agent receives both the question and junior's answer
3. Senior provides quick validation (approved/rejected/needs_revision)

## Example Use Cases

### 1. Technical Support

```bash
curl -X POST http://localhost:8001/api/support/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "How do I configure two-factor authentication?",
    "category": "technical",
    "context": "User wants to secure their account"
  }'
```

### 2. Billing Question

```bash
curl -X POST http://localhost:8001/api/support/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Why was I charged twice this month?",
    "category": "billing",
    "context": "Premium subscription customer"
  }'
```

### 3. Product Information

```bash
curl -X POST http://localhost:8001/api/support/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is the difference between the Basic and Pro plans?",
    "category": "product",
    "context": ""
  }'
```

### 4. General Support

```bash
curl -X POST http://localhost:8001/api/support/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "How do I export my data?",
    "category": "general",
    "context": "User wants to backup their information"
  }'
```

## Extending the Example

To enhance the collaboration:

1. **Add Iteration**: Allow junior to revise based on senior feedback
2. **Add Knowledge Base**: Connect to real documentation/FAQs
3. **Add Persistence**: Store sessions in a database
4. **Add Metrics**: Track approval rates, response times, and quality scores
5. **Add Categories**: Specialize agents for different support domains
6. **Add Learning**: Use feedback to improve junior agent over time

## Model Selection

The example uses different model sizes and token limits:

- **7B Model (Junior)**: Faster inference, generates detailed content (max_tokens=2000)
- **32B Model (Senior)**: Better reasoning, quick validation (max_tokens=200)

You can experiment with different models:
- Smaller models: `Qwen/Qwen2.5-3B-Instruct`, `Qwen/Qwen2.5-1.5B-Instruct`
- Larger models: `Qwen/Qwen2.5-72B-Instruct`
- Other providers: Adjust `model_provider` in settings

**Key insight**: The token limit difference (2000 vs 200) enforces the usage pattern where junior produces many tokens and senior produces few.

## Performance Considerations

- **Junior Agent**: ~3-8 seconds for detailed answer generation (7B model, 300-800 tokens)
- **Senior Agent**: ~1-2 seconds for validation (32B model, 20-50 tokens)
- **Total**: ~4-10 seconds per complete Q&A session

**Why this is efficient:**
- Junior uses fast model for heavy token generation
- Senior uses slow model but only for brief validation
- Total time is dominated by junior's generation, not senior's validation

For production use, consider:
- Caching common questions/answers
- Async processing for non-urgent questions
- Load balancing across multiple vLLM instances
- Streaming responses for better UX

## Troubleshooting

### Port already in use

```bash
python -m uvicorn src.main:app --port 8002
```

### vLLM connection errors

Ensure your vLLM instance is running and accessible:

```bash
curl https://your-vllm-instance.com/v1/models
```

### Module not found errors

Ensure the framework is installed:

```bash
pip install -e .
```

### Agent not responding

Check the logs for detailed error messages:

```bash
tail -f logs/app.log
```

## License

MIT License - See LICENSE file for details

## Support

For issues or questions about the framework, see the main [Blueprint Agents documentation](../../README.md).
