curl -X POST https://avs-vllm.q14.net/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${VLLM_API_KEY}" \
  --data @request.json
