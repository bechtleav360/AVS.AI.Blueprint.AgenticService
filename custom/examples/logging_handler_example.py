#!/usr/bin/env python3
"""
Example: Using LoggingHandler for debugging event flow.

This demonstrates how to use the built-in LoggingHandler to inspect
incoming events in your agent pipeline.
"""

import asyncio
from datetime import datetime
from uuid import uuid4

from base.src.agent import DecisionEngine, LoggingHandler
from base.src.models import GenericCloudEvent


async def main():
    """Demonstrate LoggingHandler usage."""
    print("LoggingHandler Example")
    print("=" * 70)

    # Create decision engine
    engine = DecisionEngine()

    # Add LoggingHandler with high priority (runs first)
    logging_handler = LoggingHandler(priority=10, log_level="INFO")
    engine.add_handler(logging_handler)

    # Create a sample CloudEvent
    event = GenericCloudEvent(
        id=str(uuid4()),
        source="asset-inventory",
        type="resource.check.requested",
        subject="vm-12345",
        time=datetime.utcnow(),
        datacontenttype="application/json",
        data={
            "resource_id": "vm-12345",
            "resource_type": "virtual_machine",
            "tags": {
                "environment": "production",
                "owner": "team-platform",
            },
            "attributes": {
                "has_backup": False,
                "is_encrypted": False,
            },
        },
    )

    # Process event through the chain
    print("\n🚀 Processing event through decision engine...\n")

    context = {"correlation_id": str(uuid4()), "tenant_id": "tenant-123"}

    result = await engine.process(event, context)

    print(f"\n✅ Processing complete. Result: {result}")
    print("\n" + "=" * 70)
    print("\nThe LoggingHandler printed the event details above.")
    print("You can add it to any handler chain for debugging!")


if __name__ == "__main__":
    asyncio.run(main())
