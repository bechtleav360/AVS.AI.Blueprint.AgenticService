#!/usr/bin/env python3
"""
Test script to publish an event to RabbitMQ via Dapr.
This simulates an event from the connector.
"""

import json
import requests
import sys

# Dapr pub/sub endpoint
DAPR_HTTP_PORT = 3500
PUBSUB_NAME = "rabbitmq-pubsub"
TOPIC = "Asset-Discovered-Event"

# Sample event payload matching HarmonizingInputPayload
payload = {
    "subject": None,
    "data": {
        "type": "hardware",
        "properties": {
            "id": "S4905156",
            "description": "HP EliteBook 8 Flip G1i 13 U5 16/512 GB that is ultra awesome!",
            "item_type": "Notebooks"
        }
    }
}

def publish_event():
    """Publish event to RabbitMQ via Dapr."""
    url = f"http://localhost:{DAPR_HTTP_PORT}/v1.0/publish/{PUBSUB_NAME}/{TOPIC}"

    print(f"📤 Publishing event to: {url}")
    print(f"📦 Payload:")
    print(json.dumps(payload, indent=2))
    print()

    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"}
        )

        if response.status_code == 204:
            print("✅ Event published successfully!")
            print(f"   Status: {response.status_code}")
            return True
        else:
            print(f"❌ Failed to publish event")
            print(f"   Status: {response.status_code}")
            print(f"   Response: {response.text}")
            return False

    except requests.exceptions.ConnectionError:
        print("❌ Connection failed!")
        print("   Make sure Dapr is running with: dapr run --app-id harmonizing-agent --app-port 8001 --dapr-http-port 3500 ...")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    success = publish_event()
    sys.exit(0 if success else 1)
