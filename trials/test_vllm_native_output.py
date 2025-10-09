"""Minimal test script to debug vLLM NativeOutput hanging issue."""

import asyncio
import logging
from pydantic import BaseModel
from openai import AsyncOpenAI
from pydantic_ai import Agent, NativeOutput
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.profiles import ModelProfile
import httpx

# Enable debug logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logging.getLogger("openai").setLevel(logging.DEBUG)
logging.getLogger("httpx").setLevel(logging.DEBUG)
logging.getLogger("httpcore").setLevel(logging.DEBUG)
logging.getLogger("pydantic_ai").setLevel(logging.DEBUG)


# Define a simple output model
class SimpleResult(BaseModel):
    """A simple result model."""

    message: str
    value: int


async def test_vllm_native_output():
    """Test vLLM with NativeOutput mode."""
    print("\n=== Testing vLLM with NativeOutput ===\n")

    # Configure HTTP client to prefer IPv4
    http_client = httpx.AsyncClient(
        transport=httpx.AsyncHTTPTransport(
            local_address="0.0.0.0",  # Force IPv4
        ),
        timeout=60.0,
    )

    # Configure vLLM client
    client = AsyncOpenAI(
        max_retries=1,
        base_url="https://avs-vllm.q14.net/v1",
        api_key="6FEDGzTQd8Oea8OO4onA",
        timeout=60.0,  # 60 second timeout
        http_client=http_client,
    )

    provider = OpenAIProvider(openai_client=client)

    # Configure profile with native output support
    # vLLM uses _<think>...</think> tags for reasoning
    vllm_profile = ModelProfile(
        thinking_tags=("_<think>", "</think>"),
        ignore_streamed_leading_whitespace=True,
        supports_json_schema_output=True,
        default_structured_output_mode="native",
    )

    model = OpenAIChatModel(
        provider=provider,
        model_name="default",
        profile=vllm_profile,
    )

    print("Model configured with NativeOutput support")

    # Create agent with NativeOutput
    agent = Agent(
        model=model,
        output_type=NativeOutput(
            SimpleResult, name="simple_result", description="Return a simple result"
        ),
        system_prompt="You are a helpful assistant that returns structured data.",
    )

    print("Agent created with NativeOutput")

    try:
        print("\nStarting agent.run()...")
        print("Waiting for response with 30s timeout...")
        result = await asyncio.wait_for(
            agent.run("Return a message saying 'hello' and value 42"),
            timeout=30.0
        )
        print(f"\n✓ Success! Result: {result.output}")
        return result.output
    except asyncio.TimeoutError:
        print("\n✗ TIMEOUT: Agent.run() timed out after 30 seconds")
        print("The HTTP request completed but response processing hung")
        raise
    except Exception as e:
        print(f"\n✗ ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        raise


async def test_vllm_tool_output():
    """Test vLLM with default ToolOutput mode for comparison."""
    print("\n=== Testing vLLM with ToolOutput (default) ===\n")

    # Configure HTTP client to prefer IPv4
    http_client = httpx.AsyncClient(
        transport=httpx.AsyncHTTPTransport(
            local_address="0.0.0.0",  # Force IPv4
        ),
        timeout=60.0,
    )

    # Configure vLLM client
    client = AsyncOpenAI(
        max_retries=1,
        base_url="https://avs-vllm.q14.net/v1",
        api_key="6FEDGzTQd8Oea8OO4onA",
        timeout=60.0,
        http_client=http_client,
    )

    provider = OpenAIProvider(openai_client=client)

    # Configure profile WITHOUT native output support
    # vLLM uses <think>...</think> tags for reasoning in tool mode
    vllm_profile = ModelProfile(
        thinking_tags=("<think>", "</think>"),
        ignore_streamed_leading_whitespace=True,
        supports_json_schema_output=False,  # Disable native output
        default_structured_output_mode="tool",  # Use tool mode
    )

    model = OpenAIChatModel(
        provider=provider,
        model_name="default",
        profile=vllm_profile,
    )

    print("Model configured with ToolOutput (default)")

    # Create agent with default ToolOutput
    agent = Agent(
        model=model,
        output_type=SimpleResult,  # No wrapper = ToolOutput mode
        system_prompt="You are a helpful assistant that returns structured data.",
    )

    print("Agent created with ToolOutput")

    try:
        print("\nStarting agent.run()...")
        result = await agent.run("Return a message saying 'hello' and value 42")
        print(f"\n✓ Success! Result: {result.output}")
        return result.output
    except asyncio.TimeoutError:
        print("\n✗ TIMEOUT: Agent.run() timed out")
        raise
    except Exception as e:
        print(f"\n✗ ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        raise


async def main():
    """Run both tests."""
    print("=" * 60)
    print("vLLM Output Mode Comparison Test")
    print("=" * 60)

    # Test 1: NativeOutput
    try:
        await test_vllm_native_output()
    except Exception as e:
        print(f"\nNativeOutput test failed: {e}")

    print("\n" + "=" * 60 + "\n")

    # Test 2: ToolOutput
    try:
        await test_vllm_tool_output()
    except Exception as e:
        print(f"\nToolOutput test failed: {e}")

    print("\n" + "=" * 60)
    print("Test completed")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
