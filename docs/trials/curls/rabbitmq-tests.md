
# RabbitMQ Connection Test

## 1. Start port-forward (in separate terminal)
```bash
kubectl port-forward -n dev-bios-bechtle svc/rabbitmq 5672:5672 15672:15672
```

## 2. Test Python connection
```bash
python trials/test_rabbitmq_connection.py
```

## 3. Access RabbitMQ Management UI
Open browser: http://localhost:15672
- Username: `default_user_gL_0b5UoGT7HlwnDWib`
- Password: `HJ7PBBqNljN4KWMsXOtQ97LPuqaX7pBb`

## 4. Test Dapr pubsub (after starting service with Dapr)
```bash
# Publish a test message via Dapr
curl -X POST http://localhost:3500/v1.0/publish/rabbitmq-pubsub/invoice.events \
  -H "Content-Type: application/json" \
  -d '{
    "invoice_text": "Invoice #TEST-001\nAmount: 100.00 EUR",
    "details": {"action": "invoke_agent", "source": "test"}
  }'
```

## 5. Test agent endpoint with RabbitMQ
```bash
# Direct REST API call
curl -X POST http://localhost:8001/api/process-resource \
  -H "Content-Type: application/json" \
  -d '{
    "invoice_text": "Invoice #INV-2025-001\nDate: 2025-01-15\nCustomer: Bechtle AG\n\nLine Items:\n1. Consulting services - Qty: 10 hrs @ 150.00 EUR/hr\n2. Software license - Qty: 1 @ 500.00 EUR\n\nSubtotal: 2000.00 EUR\nTax (19%): 380.00 EUR\nTotal: 2380.00 EUR",
    "details": {"action": "invoke_agent", "source": "curl_test"}
  }'
```
