# OpenTelemetry Configuration

**Complete guide to configuring observability with OpenTelemetry**

OpenTelemetry provides distributed tracing, metrics, and logging for your agent.

## What is OpenTelemetry?

**OpenTelemetry (OTel)** is an observability framework that provides:
- ✅ **Distributed Tracing** - Track requests across services
- ✅ **Metrics** - Collect performance data
- ✅ **Logging** - Structured log correlation
- ✅ **Context Propagation** - Link related operations
- ✅ **Vendor Neutral** - Works with any backend

## Why Use OpenTelemetry?

**Benefits:**
- See request flow through your system
- Identify performance bottlenecks
- Debug production issues
- Monitor service health
- Correlate logs with traces

**Example trace:**
```
process_event (200ms)
  ├─ handler.ValidationHandler (10ms)
  ├─ handler.AgentInvokerHandler (5ms)
  └─ agent.InvoiceAgent.run (180ms)
      ├─ llm.chat_completion (150ms)
      └─ tool.calculate_invoice (25ms)
```

## Basic Configuration

### Enable OpenTelemetry

```toml
# settings.toml
[default]
otel_enabled = true
otel_service_name = "invoice-processor"
otel_endpoint = "http://localhost:4317"  # OTLP gRPC endpoint
```

### Disable OpenTelemetry

```toml
[default]
otel_enabled = false
```

Or via environment variable:
```bash
export OTEL_ENABLED=false
```

## Configuration Options

### Service Identification

```toml
[default]
# Service name (appears in traces)
otel_service_name = "invoice-processor"

# Service version
otel_service_version = "1.0.0"

# Deployment environment
otel_deployment_environment = "production"
```

```bash
# Via environment variables
export OTEL_SERVICE_NAME="invoice-processor"
export OTEL_SERVICE_VERSION="1.0.0"
export OTEL_RESOURCE_ATTRIBUTES="environment=production,team=platform"
```

### Exporter Configuration

#### OTLP gRPC (Recommended)

```toml
[default]
otel_endpoint = "http://localhost:4317"
otel_exporter_protocol = "grpc"
```

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4317"
export OTEL_EXPORTER_OTLP_PROTOCOL="grpc"
```

#### OTLP HTTP

```toml
[default]
otel_endpoint = "http://localhost:4318"
otel_exporter_protocol = "http/protobuf"
```

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
```

#### Jaeger

```bash
export OTEL_TRACES_EXPORTER="jaeger"
export OTEL_EXPORTER_JAEGER_ENDPOINT="http://localhost:14250"
```

#### Zipkin

```bash
export OTEL_TRACES_EXPORTER="zipkin"
export OTEL_EXPORTER_ZIPKIN_ENDPOINT="http://localhost:9411/api/v2/spans"
```

### Authentication

#### API Key

```bash
export OTEL_EXPORTER_OTLP_HEADERS="api-key=your-api-key"
```

#### Bearer Token

```bash
export OTEL_EXPORTER_OTLP_HEADERS="authorization=Bearer your-token"
```

#### Multiple Headers

```bash
export OTEL_EXPORTER_OTLP_HEADERS="api-key=key123,x-custom-header=value"
```

## Sampling Configuration

### Always Sample (Development)

```bash
export OTEL_TRACES_SAMPLER="always_on"
```

### Never Sample

```bash
export OTEL_TRACES_SAMPLER="always_off"
```

### Ratio-Based Sampling

Sample a percentage of traces:

```bash
# Sample 10% of traces
export OTEL_TRACES_SAMPLER="traceidratio"
export OTEL_TRACES_SAMPLER_ARG="0.1"
```

### Parent-Based Sampling

Respect parent span sampling decision:

```bash
# If parent is sampled, sample this trace
export OTEL_TRACES_SAMPLER="parentbased_traceidratio"
export OTEL_TRACES_SAMPLER_ARG="0.1"
```

**Recommended for production:**
```bash
export OTEL_TRACES_SAMPLER="parentbased_traceidratio"
export OTEL_TRACES_SAMPLER_ARG="0.1"  # 10% sampling
```

## Resource Attributes

Add metadata to all traces:

```bash
export OTEL_RESOURCE_ATTRIBUTES="environment=production,version=1.0.0,team=platform,region=eu-west-1"
```

```toml
[production]
otel_resource_attributes = "environment=production,version=1.0.0,team=platform"
```

**Common attributes:**
- `environment` - deployment environment
- `version` - application version
- `team` - owning team
- `region` - deployment region
- `host.name` - hostname
- `service.namespace` - service group

## Trace Configuration

### Span Limits

```bash
# Maximum number of attributes per span
export OTEL_SPAN_ATTRIBUTE_COUNT_LIMIT=128

# Maximum number of events per span
export OTEL_SPAN_EVENT_COUNT_LIMIT=128

# Maximum number of links per span
export OTEL_SPAN_LINK_COUNT_LIMIT=128
```

### Batch Processing

```bash
# Maximum batch size
export OTEL_BSP_MAX_EXPORT_BATCH_SIZE=512

# Maximum queue size
export OTEL_BSP_MAX_QUEUE_SIZE=2048

# Export timeout (ms)
export OTEL_BSP_EXPORT_TIMEOUT=30000

# Schedule delay (ms)
export OTEL_BSP_SCHEDULE_DELAY=5000
```

## Backend-Specific Configuration

### Jaeger

```bash
# All-in-one setup
export OTEL_TRACES_EXPORTER="jaeger"
export OTEL_EXPORTER_JAEGER_ENDPOINT="http://localhost:14250"
export OTEL_EXPORTER_JAEGER_AGENT_HOST="localhost"
export OTEL_EXPORTER_JAEGER_AGENT_PORT="6831"
```

### Zipkin

```bash
export OTEL_TRACES_EXPORTER="zipkin"
export OTEL_EXPORTER_ZIPKIN_ENDPOINT="http://localhost:9411/api/v2/spans"
```

### Datadog

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="https://api.datadoghq.com"
export OTEL_EXPORTER_OTLP_HEADERS="dd-api-key=your-datadog-api-key"
export OTEL_RESOURCE_ATTRIBUTES="service.name=invoice-processor,env=production"
```

### New Relic

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="https://otlp.nr-data.net:4317"
export OTEL_EXPORTER_OTLP_HEADERS="api-key=your-newrelic-license-key"
```

### Honeycomb

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="https://api.honeycomb.io"
export OTEL_EXPORTER_OTLP_HEADERS="x-honeycomb-team=your-api-key"
```

### Grafana Cloud

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="https://otlp-gateway-prod-eu-west-0.grafana.net/otlp"
export OTEL_EXPORTER_OTLP_HEADERS="authorization=Basic base64-encoded-credentials"
```

## Environment-Specific Configuration

### Development

```toml
[development]
otel_enabled = true
otel_service_name = "invoice-processor-dev"
otel_endpoint = "http://localhost:4317"
```

```bash
export OTEL_TRACES_SAMPLER="always_on"  # Sample everything
export OTEL_LOG_LEVEL="debug"
```

### Staging

```toml
[staging]
otel_enabled = true
otel_service_name = "invoice-processor-staging"
otel_endpoint = "https://otel-collector.staging.example.com"
```

```bash
export OTEL_TRACES_SAMPLER="parentbased_traceidratio"
export OTEL_TRACES_SAMPLER_ARG="0.5"  # 50% sampling
```

### Production

```toml
[production]
otel_enabled = true
otel_service_name = "invoice-processor"
otel_endpoint = "https://otel-collector.prod.example.com"
otel_resource_attributes = "environment=production,version=1.0.0"
```

```bash
export OTEL_TRACES_SAMPLER="parentbased_traceidratio"
export OTEL_TRACES_SAMPLER_ARG="0.1"  # 10% sampling
export OTEL_EXPORTER_OTLP_HEADERS="api-key=prod-key"
```

## Custom Instrumentation

### Add Custom Spans

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

async def process_invoice(invoice_id: str):
    """Process invoice with custom tracing."""
    with tracer.start_as_current_span("process_invoice") as span:
        # Add attributes
        span.set_attribute("invoice.id", invoice_id)
        span.set_attribute("invoice.amount", 1000.00)
        
        # Your processing logic
        result = await do_processing(invoice_id)
        
        # Add result attributes
        span.set_attribute("result.status", result.status)
        
        return result
```

### Add Events

```python
with tracer.start_as_current_span("process_invoice") as span:
    # Add event
    span.add_event("validation_started")
    
    validate(invoice)
    
    span.add_event("validation_completed", {
        "validation.result": "success"
    })
```

### Record Exceptions

```python
with tracer.start_as_current_span("process_invoice") as span:
    try:
        result = await process(invoice)
    except Exception as e:
        # Record exception in span
        span.record_exception(e)
        span.set_status(trace.Status(trace.StatusCode.ERROR))
        raise
```

### Link Spans

```python
from opentelemetry.trace import Link

# Create link to related span
link = Link(context=related_span_context)

with tracer.start_as_current_span("process_invoice", links=[link]) as span:
    # Processing...
    pass
```

## Viewing Traces

### Local Development with Jaeger

**Start Jaeger:**
```bash
docker run -d --name jaeger \
  -p 16686:16686 \
  -p 4317:4317 \
  jaegertracing/all-in-one:latest
```

**Configure agent:**
```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4317"
```

**View traces:**
Open http://localhost:16686

### Local Development with Zipkin

**Start Zipkin:**
```bash
docker run -d --name zipkin \
  -p 9411:9411 \
  openzipkin/zipkin
```

**Configure agent:**
```bash
export OTEL_TRACES_EXPORTER="zipkin"
export OTEL_EXPORTER_ZIPKIN_ENDPOINT="http://localhost:9411/api/v2/spans"
```

**View traces:**
Open http://localhost:9411

## Performance Considerations

### Reduce Overhead

```bash
# Lower sampling rate
export OTEL_TRACES_SAMPLER_ARG="0.01"  # 1% sampling

# Increase batch size
export OTEL_BSP_MAX_EXPORT_BATCH_SIZE=2048

# Increase schedule delay
export OTEL_BSP_SCHEDULE_DELAY=10000  # 10 seconds
```

### Async Export

Traces are exported asynchronously by default, so they don't block your application.

### Disable in Tests

```python
# In tests
import os
os.environ["OTEL_ENABLED"] = "false"
```

## Troubleshooting

### Traces Not Appearing

**Check:**
1. OTel enabled: `echo $OTEL_ENABLED`
2. Endpoint correct: `echo $OTEL_EXPORTER_OTLP_ENDPOINT`
3. Collector running: `curl http://localhost:4317`
4. Sampling enabled: `echo $OTEL_TRACES_SAMPLER`

**Debug:**
```bash
# Enable debug logging
export OTEL_LOG_LEVEL="debug"
export OTEL_PYTHON_LOG_LEVEL="debug"

# Run agent and check logs
python -m uvicorn custom.src.main:app
```

### Connection Errors

**Check:**
1. Endpoint reachable: `curl http://localhost:4317`
2. Firewall rules
3. Network connectivity

**Test:**
```bash
# Test OTLP endpoint
grpcurl -plaintext localhost:4317 list
```

### High Memory Usage

**Reduce:**
```bash
# Lower queue size
export OTEL_BSP_MAX_QUEUE_SIZE=512

# Lower batch size
export OTEL_BSP_MAX_EXPORT_BATCH_SIZE=256

# Increase export frequency
export OTEL_BSP_SCHEDULE_DELAY=1000
```

### Spans Missing Attributes

**Check span limits:**
```bash
export OTEL_SPAN_ATTRIBUTE_COUNT_LIMIT=256
export OTEL_SPAN_EVENT_COUNT_LIMIT=256
```

## Best Practices

### 1. Use Meaningful Span Names

✅ **Good:**
```python
with tracer.start_as_current_span("process_invoice"):
with tracer.start_as_current_span("validate_customer"):
with tracer.start_as_current_span("calculate_totals"):
```

❌ **Bad:**
```python
with tracer.start_as_current_span("function1"):
with tracer.start_as_current_span("do_stuff"):
```

### 2. Add Relevant Attributes

```python
span.set_attribute("invoice.id", invoice_id)
span.set_attribute("invoice.amount", amount)
span.set_attribute("customer.id", customer_id)
span.set_attribute("result.status", status)
```

### 3. Sample Appropriately

- **Development:** 100% (`always_on`)
- **Staging:** 50% (`traceidratio=0.5`)
- **Production:** 1-10% (`traceidratio=0.01-0.1`)

### 4. Use Resource Attributes

```bash
export OTEL_RESOURCE_ATTRIBUTES="environment=prod,version=1.0.0,team=platform"
```

### 5. Record Exceptions

```python
try:
    result = process()
except Exception as e:
    span.record_exception(e)
    span.set_status(trace.Status(trace.StatusCode.ERROR))
    raise
```

### 6. Don't Over-Instrument

Only add spans for meaningful operations:
- API calls
- Database queries
- External service calls
- Business logic steps

Don't add spans for:
- Simple getters/setters
- Trivial calculations
- Every function call

## Example Configurations

### Minimal (Development)

```bash
export OTEL_ENABLED=true
export OTEL_SERVICE_NAME="my-agent"
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4317"
```

### Production with Jaeger

```bash
export OTEL_ENABLED=true
export OTEL_SERVICE_NAME="invoice-processor"
export OTEL_EXPORTER_OTLP_ENDPOINT="https://jaeger-collector.prod.example.com:4317"
export OTEL_TRACES_SAMPLER="parentbased_traceidratio"
export OTEL_TRACES_SAMPLER_ARG="0.1"
export OTEL_RESOURCE_ATTRIBUTES="environment=production,version=1.0.0,region=eu-west-1"
```

### Production with Datadog

```bash
export OTEL_ENABLED=true
export OTEL_SERVICE_NAME="invoice-processor"
export OTEL_EXPORTER_OTLP_ENDPOINT="https://api.datadoghq.com"
export OTEL_EXPORTER_OTLP_HEADERS="dd-api-key=your-api-key"
export OTEL_TRACES_SAMPLER="parentbased_traceidratio"
export OTEL_TRACES_SAMPLER_ARG="0.05"
export OTEL_RESOURCE_ATTRIBUTES="service.name=invoice-processor,env=production,version=1.0.0"
```

## See Also

- [Agent Configuration](agent-configuration.md) - Complete agent settings
- [Dynaconf](dynaconf.md) - Configuration management
- [Architecture Overview](../architecture.md) - System design
