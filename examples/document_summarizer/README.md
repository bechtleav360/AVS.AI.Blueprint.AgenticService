# Document Summarizer

A document summarization service built with the Blueprint Agents framework. Demonstrates LLM agent integration with structured output, tool usage, and prompt management.

## Features

- Structured document summaries using Pydantic models
- Tool-augmented analysis (word count, metadata extraction)
- Persistent caching of summaries
- REST API for submitting documents and retrieving results

## Setup

1. Install dependencies:

```bash
pip install -e .
```

2. Configure your API key by copying the example secrets file:

```bash
cp secrets.toml.example secrets.toml
```

Edit `secrets.toml` and replace the placeholder with your OpenAI API key:

```toml
[default.runtimes.document_summarizer]
model_api_key = "sk-your-actual-openai-api-key"
```

3. Run the service:

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

## API Usage

### Summarize a Document

```bash
curl -X POST http://localhost:8000/api/summarize \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Artificial intelligence has transformed industries worldwide. From healthcare diagnostics to autonomous vehicles, AI systems are becoming integral to modern life. Recent advances in large language models have opened new possibilities for natural language understanding and generation.",
    "title": "AI Industry Overview"
  }'
```

### Retrieve a Cached Summary

```bash
curl http://localhost:8000/api/summaries/{document_id}
```

## Configuration

Model settings are in `settings.toml`. The default configuration uses `gpt-4o-mini` with a temperature of 0.3 for consistent summaries. Adjust `model_temperature`, `model_max_tokens`, and other parameters as needed.

## Running Tests

```bash
pytest tests/
```
