# TODO

## vLLM Tool Calling Remediation
- **Disable tool-calling fallback (Option B)**
  - Reconfigure the agent to accept plain JSON output from the model and invoke `calculate_invoice()` manually.
  - Update the invoice agent workflow documentation to describe the non-tool mode.
- **Implement response-proxy workaround (Option C)**
  - Build an HTTP shim that strips `<think>`/`<tool_call>` tags and converts them into OpenAI-compatible JSON before forwarding to `pydantic_ai`.
  - Add integration tests that confirm the shim emits clean `tool_calls` payloads.
- **Track upstream fix**
  - Monitor Hermes/vLLM releases for native compliance with OpenAI tool-calling JSON.
  - Remove temporary workarounds once the upstream fix lands and passes regression tests.

## References
- **Key files**: `DEBUG_TOOL_CALLING.md`, `base/src/agent/base_agent.py`, `custom/src/models/resource.py`
- **Last known error**: vLLM 400 response with `Invalid JSON: expected value at line 1 column 1` caused by `<think>...</think>` + `<tool_call>` output.

## RabbitMQ PubSub Connectivity
- **Symptom**: `dapr run` fails with `INIT_COMPONENT_FAILURE` (403 or connection refused) when initializing `rabbitmq-pubsub` on localhost port-forward.
- **Status**: Credentials sourced from `secrets.toml`, but cluster port-forward to `svc/rabbitmq` resets connections; temporarily using `kubectl port-forward pod/rabbitmq-server-0 5672:5672 15672:15672`.
- **Next steps**:
  - Investigate stable forwarding (service vs pod) or expose RabbitMQ via ingress.
  - Confirm final Dapr component format (host/vHost vs connectionString) once connectivity stabilizes.
  - Add automated health check for RabbitMQ sidecar startup.
