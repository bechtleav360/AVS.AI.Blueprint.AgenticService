#!/usr/bin/env python3
"""Test RabbitMQ connection from Kubernetes port-forward."""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    import pika
except ImportError:
    print("Installing pika...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pika"])
    import pika

def test_rabbitmq_connection():
    """Test connection to RabbitMQ via port-forward."""
    
    # Load credentials from .env.rabbitmq
    env_file = project_root / ".env.rabbitmq"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                if line.strip() and not line.startswith("#"):
                    key, value = line.strip().split("=", 1)
                    os.environ[key] = value
    
    host = os.getenv("RABBITMQ_HOST", "localhost")
    port = int(os.getenv("RABBITMQ_PORT", "5672"))
    username = os.getenv("RABBITMQ_USERNAME", "guest")
    password = os.getenv("RABBITMQ_PASSWORD", "guest")
    vhost = os.getenv("RABBITMQ_VHOST", "/")
    
    print(f"Testing RabbitMQ connection to {host}:{port}")
    print(f"Username: {username}")
    print(f"VHost: {vhost}")
    
    try:
        # Create credentials
        credentials = pika.PlainCredentials(username, password)
        
        # Connection parameters
        parameters = pika.ConnectionParameters(
            host=host,
            port=port,
            virtual_host=vhost,
            credentials=credentials,
            heartbeat=600,
            blocked_connection_timeout=300,
        )
        
        # Attempt connection
        print("\nConnecting...")
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        
        # Declare a test queue
        test_queue = "test-connection-queue"
        channel.queue_declare(queue=test_queue, durable=True)
        print(f"✓ Successfully declared queue: {test_queue}")
        
        # Publish a test message
        channel.basic_publish(
            exchange="",
            routing_key=test_queue,
            body=b"Test message from connection test",
            properties=pika.BasicProperties(delivery_mode=2),  # Persistent
        )
        print(f"✓ Successfully published test message")
        
        # Consume the message
        method_frame, header_frame, body = channel.basic_get(queue=test_queue)
        if method_frame:
            print(f"✓ Successfully consumed message: {body.decode()}")
            channel.basic_ack(method_frame.delivery_tag)
        else:
            print("⚠ No message in queue")
        
        # Clean up
        channel.queue_delete(queue=test_queue)
        print(f"✓ Cleaned up test queue")
        
        connection.close()
        print("\n✓ RabbitMQ connection test PASSED")
        return True
        
    except pika.exceptions.AMQPConnectionError as e:
        print(f"\n✗ Connection failed: {e}")
        print("\nTroubleshooting:")
        print("1. Ensure port-forward is running:")
        print("   kubectl port-forward -n dev-bios-bechtle svc/rabbitmq 5672:5672 15672:15672")
        print("2. Check credentials in .env.rabbitmq")
        print("3. Verify RabbitMQ is running:")
        print("   kubectl get pods -n dev-bios-bechtle | grep rabbit")
        return False
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_rabbitmq_connection()
    sys.exit(0 if success else 1)
