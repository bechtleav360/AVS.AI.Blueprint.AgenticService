#!/usr/bin/env python3
"""
Pydantic AI Trial - Simple agent with tools

This demonstrates the minimal setup needed to create a Pydantic AI agent
that uses tools to analyze resources.

Set environment variables for configuration:
    OPENAI_API_KEY - Your OpenAI API key
    OPENAI_BASE_URL - Optional: Custom endpoint (e.g., vLLM)
"""

import asyncio
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext


# ============================================================================
# MODELS
# ============================================================================


class Resource(BaseModel):
    """Resource to analyze."""

    id: str
    name: str
    has_backup: bool = False
    is_encrypted: bool = False


class Analysis(BaseModel):
    """Analysis result."""

    resource_id: str
    status: str  # "ok" or "issues"
    message: str


# ============================================================================
# TOOL
# ============================================================================


async def check_resource(ctx: RunContext[None], resource: Resource) -> Analysis:
    """Check if resource meets requirements."""
    print(f"🔧 Checking resource: {resource.id}")

    issues = []
    if not resource.has_backup:
        issues.append("no backup")
    if not resource.is_encrypted:
        issues.append("not encrypted")

    if issues:
        return Analysis(
            resource_id=resource.id,
            status="issues",
            message=f"Found issues: {', '.join(issues)}",
        )

    return Analysis(resource_id=resource.id, status="ok", message="All checks passed")


# ============================================================================
# AGENT
# ============================================================================


def create_agent() -> Agent[None, Analysis]:
    """Create the agent."""

    # Modern approach: pass model string directly to Agent
    # Agent will handle model initialization internally
    agent = Agent(
        "openai:gpt-4o",  # Model string format: 'provider:model-name'
        result_type=Analysis,
        system_prompt="You check resources. Use the check_resource tool and explain the results.",
    )

    # Register tools using decorator
    agent.tool(check_resource)

    return agent


# ============================================================================
# MAIN
# ============================================================================


async def main():
    print("Pydantic AI Trial\n" + "=" * 50)

    agent = create_agent()

    # Test 1: Resource with issues
    resource1 = Resource(
        id="vm-1", name="web-server", has_backup=False, is_encrypted=False
    )

    print(f"\n📋 Analyzing: {resource1.name}")
    result1 = await agent.run(f"Check this resource: {resource1.model_dump_json()}")

    print(f"✅ Result:")
    print(f"   Status: {result1.data.status}")
    print(f"   Message: {result1.data.message}")

    # Test 2: Resource OK
    resource2 = Resource(id="db-1", name="database", has_backup=True, is_encrypted=True)

    print(f"\n📋 Analyzing: {resource2.name}")
    result2 = await agent.run(f"Check this resource: {resource2.model_dump_json()}")

    print(f"✅ Result:")
    print(f"   Status: {result2.data.status}")
    print(f"   Message: {result2.data.message}")

    print("\n" + "=" * 50)
    print("Done! Modify this script to test your own logic.")


if __name__ == "__main__":
    asyncio.run(main())
