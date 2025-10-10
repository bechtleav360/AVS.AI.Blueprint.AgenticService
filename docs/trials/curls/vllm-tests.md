# List available models
curl -X GET https://avs-vllm.q14.net/v1/models \
  -H "Authorization: Bearer ${VLLM_API_KEY}"

curl -X GET https://avs-vllm.q14.net/v1/models \
  -H "Authorization: Bearer none"

# Chat completion request
curl -X POST https://avs-vllm.q14.net/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${VLLM_API_KEY}" \
  --data @request.json

curl -X POST https://avs-vllm.q14.net/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer none" \
  --data @request.json

# Embeddings request
curl -X POST https://avs-vllm.q14.net/v1/embeddings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${VLLM_API_KEY}" \
  --data '{
    "model": "Qwen/Qwen2.5-32B-Instruct-AWQ",
    "input": ["Example text to embed"]
  }'

# Sanity check
curl -sS https://avs-vllm.q14.net/v1/chat/completions \
  -H "Authorization: Bearer ${VLLM_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "default",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "Reply with the word PONG."}
    ],
    "max_tokens": 64
  }' | jq .



curl -sS https://avs-vllm.q14.net/v1/chat/completions \
  -H "Authorization: Bearer ${VLLM_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "default",
    "temperature": 0,
    "top_p": 0.1,
    "max_tokens": 5,
    "stop": ["\n"],
    "messages": [
      {"role": "system", "content": "Reply with exactly: PONG"},
      {"role": "user", "content": "PONG"}
    ]
  }' | jq .

---

# Tool call

curl -sS https://avs-vllm.q14.net/v1/chat/completions \
  -H "Authorization: Bearer ${VLLM_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "default",
    "tool_choice": "auto",
    "messages": [
      {
        "role": "system",
        "content": "You extract invoice fields from OCR text, then MUST call the calculate_invoice tool with an InvoiceInput."
      },
      {
        "role": "user",
        "content": "Invoice #INV-2025-001\nDate: 2025-01-15\nCustomer: Bechtle AG\n\nLine Items:\n1. Consulting services - Qty: 10 hrs @ 150.00 EUR/hr\n2. Software license - Qty: 1 @ 500.00 EUR\n\nSubtotal: 2000.00 EUR\nTax (19%): 380.00 EUR\nTotal: 2380.00 EUR\nCurrency: EUR"
      }
    ],
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "calculate_invoice",
          "description": "Calculate totals and infer taxes for an invoice.",
          "parameters": {
            "type": "object",
            "properties": {
              "invoice_id": { "type": "string" },
              "currency":   { "type": "string", "enum": ["EUR","USD","GBP"], "default": "EUR" },
              "line_items": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "description": { "type": "string" },
                    "quantity":    { "type": "number" },
                    "unit_price":  { "type": "number" },
                    "tax_rate":    { "type": ["number","null"], "minimum": 0.0, "maximum": 1.0 }
                  },
                  "required": ["description","quantity","unit_price"]
                },
                "minItems": 1
              }
            },
            "required": ["invoice_id","line_items","currency"]
          }
        }
      }
    ],
    "max_tokens": 256
  }' | jq .
