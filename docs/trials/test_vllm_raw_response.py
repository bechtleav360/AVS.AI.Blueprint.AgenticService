"""Direct test of vLLM response to diagnose the hanging issue."""

import asyncio
import json
from openai import AsyncOpenAI
import httpx

async def test_raw_vllm_response():
    """Make a direct call to vLLM and inspect the raw response."""
    print("Testing raw vLLM response with json_schema...")
    
    # Configure HTTP client
    http_client = httpx.AsyncClient(
        transport=httpx.AsyncHTTPTransport(local_address="0.0.0.0"),
        timeout=60.0,
    )
    
    # Configure vLLM client
    client = AsyncOpenAI(
        base_url="https://avs-vllm.q14.net/v1",
        api_key="6FEDGzTQd8Oea8OO4onA",
        timeout=60.0,
        http_client=http_client,
    )
    
    # Define the schema
    schema = {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
            "value": {"type": "integer"}
        },
        "required": ["message", "value"]
    }
    
    try:
        print("\nSending request with response_format...")
        response = await client.chat.completions.create(
            model="default",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that returns structured data."},
                {"role": "user", "content": "Return a message saying 'hello' and value 42"}
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "simple_result",
                    "schema": schema,
                    "description": "Return a simple result",
                    "strict": None
                }
            },
            stream=False
        )
        
        print("\n✓ Response received!")
        print(f"Response type: {type(response)}")
        print(f"Response object: {response}")
        print(f"\nChoice 0: {response.choices[0]}")
        print(f"Message: {response.choices[0].message}")
        print(f"Content: {response.choices[0].message.content}")
        print(f"Finish reason: {response.choices[0].finish_reason}")
        
        # Try to parse the content
        if response.choices[0].message.content:
            try:
                parsed = json.loads(response.choices[0].message.content)
                print(f"\nParsed JSON: {parsed}")
            except json.JSONDecodeError as e:
                print(f"\n✗ Failed to parse JSON: {e}")
        
        return response
        
    except Exception as e:
        print(f"\n✗ ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        await http_client.aclose()

if __name__ == "__main__":
    asyncio.run(test_raw_vllm_response())
