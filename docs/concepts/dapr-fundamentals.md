# Dapr Fundamentals

## What is Dapr?

**Dapr** (Distributed Application Runtime) is an open-source, portable, event-driven runtime that makes it easier for developers to build resilient, microservice applications. Dapr provides APIs that address common challenges when building distributed applications such as:
- State management
- Service-to-service invocation
- Message publishing and subscribing
- Event-driven resource bindings
- Distributed observability
- Secrets management

## Motivation

### The Problem
Building distributed applications requires dealing with complex infrastructure concerns:
- **Message broker connectivity** - Different protocols, credentials, retry logic
- **Service discovery** - Finding and communicating with other services
- **State persistence** - Caching, consistency, and data durability
- **Observability** - Logging, metrics, and tracing across services
- **Resilience** - Circuit breakers, retries, and failure handling

### The Dapr Solution
Dapr abstracts these concerns behind a consistent, language-agnostic API:
- **Sidecar pattern** - Dapr runs alongside your application as a sidecar process
- **Standard APIs** - HTTP/gRPC endpoints that work the same across languages
- **Pluggable components** - Swap underlying infrastructure without code changes
- **Platform agnostic** - Runs on Kubernetes, virtual machines, or edge devices

## Architecture

### Sidecar Pattern
```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│   Application   │◄────►│   Dapr Sidecar  │◄────►│  Infrastructure │
│   (Your Code)   │      │                 │      │ (RabbitMQ)      │
└─────────────────┘      └─────────────────┘      └─────────────────┘
```

- **Local communication** - App talks to Dapr on localhost
- **Remote operations** - Dapr handles infrastructure communication
- **Isolation** - Infrastructure concerns separated from business logic

### Building Blocks

| Building Block | Purpose | Example Components |
|----------------|---------|-------------------|
| **Service Invocation** | Secure service-to-service calls | HTTP, gRPC, mTLS |
| **State Management** | Store and retrieve application state | Redis, PostgreSQL, MongoDB |
| **Publish/Subscribe** | Event-driven messaging | RabbitMQ, Kafka, Azure Service Bus |
| **Resource Bindings** | Connect to external systems | AWS S3, Twitter, SMTP |
| **Actors** | Stateful, single-threaded objects | Virtual actors, reminders |
| **Observability** | Metrics, logs, and tracing | OpenTelemetry, Zipkin |
| **Secrets** | Secure access to secrets | AWS Secrets Manager, HashiCorp Vault |

### Component Model
```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Dapr API  │◄──►│  Component  │◄──►│  Backend    │
│             │    │  Interface  │    │  Service    │
└─────────────┘    └─────────────┘    └─────────────┘
```

- **Standard interface** - All components implement the same contract
- **Swap without code changes** - Change Redis to PostgreSQL without touching application code
- **Configuration-driven** - Components defined in YAML manifests

## Benefits

### 1. **Developer Productivity**
- **Focus on business logic** - No need to learn specific SDKs for each service
- **Language agnostic** - Same APIs work for Python, Java, .NET, Go, JavaScript
- **Consistent patterns** - Learn once, apply everywhere

### 2. **Operational Excellence**
- **Observability built-in** - Automatic tracing and metrics for all Dapr operations
- **Health checks** - Built-in liveness and readiness probes
- **Configuration management** - Centralized component configuration

### 3. **Portability**
- **Multi-cloud** - Run on Azure, AWS, GCP, or on-premises
- **Multi-environment** - Same code works on Kubernetes, VMs, or edge devices
- **Vendor lock-in prevention** - Swap underlying services without code changes

### 4. **Resilience**
- **Automatic retries** - Built-in retry policies for transient failures
- **Circuit breakers** - Prevent cascading failures
- **Timeouts and dead-letter queues** - Handle failures gracefully

### 5. **Security**
- **mTLS by default** - Automatic encryption for service-to-service communication
- **Secret management** - Secure access to credentials and API keys
- **Access control** - Fine-grained permissions for Dapr APIs

## Dapr in the Agents Blueprint

### Kubernetes Integration
- **Operator-managed** - Dapr operator automatically injects sidecars
- **Namespace-scoped** - Components and configurations isolated per namespace
- **Resource-aware** - Sidecars share pod resources efficiently

### Event-Driven Architecture
- **Pub/Sub abstraction** - RabbitMQ complexity hidden behind Dapr API
- **CloudEvents standard** - Consistent event format across all services
- **Subscription management** - Declarative event subscriptions via YAML

### Development Experience
- **Local development** - Dapr CLI for local testing (optional)
- **Swagger integration** - Test event endpoints through Swagger UI
- **Observability** - Built-in tracing and metrics for event processing

## Key Concepts

### Components
Dapr components are configuration files that connect Dapr building blocks to specific infrastructure:
```yaml
apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: pubsub
spec:
  type: pubsub.rabbitmq
  version: v1
  metadata:
    - name: host
      value: "amqp://localhost:5672"
```

### Configuration
Global Dapr settings applied to all applications in a namespace:
```yaml
apiVersion: dapr.io/v1alpha1
kind: Configuration
metadata:
  name: dapr-config
spec:
  tracing:
    samplingRate: "1"
    zipkin:
      endpointAddress: "http://zipkin.default.svc.cluster.local:9411/api/v2/spans"
```

### Subscriptions
Declarative event subscriptions that route topics to application endpoints:
```yaml
apiVersion: dapr.io/v2alpha1
kind: Subscription
metadata:
  name: order-events
spec:
  pubsubname: pubsub
  topic: orders.created
  route: /events/process
```

## Best Practices

1. **Use sidecar pattern** - Keep infrastructure concerns separate from application code
2. **Leverage components** - Configure infrastructure through YAML, not code
3. **Implement idempotency** - Handle duplicate events gracefully
4. **Monitor health** - Use built-in health endpoints for observability
5. **Secure by default** - Enable mTLS and use Dapr secrets management
6. **Test locally** - Use Dapr CLI for development, then deploy to Kubernetes

## When to Use Dapr

### Ideal for:
- **Microservices architectures** - Multiple services communicating via events
- **Event-driven systems** - Applications reacting to external events
- **Multi-environment deployments** - Need to run across different platforms
- **Polyglot systems** - Services written in different programming languages
- **Cloud-native applications** - Leveraging cloud services and patterns

### Consider alternatives for:
- **Simple monoliths** - Single applications without distributed needs
- **Low-latency requirements** - Direct communication may be faster
- **Resource-constrained environments** - Sidecar adds overhead
- **Simple CRUD applications** - Traditional databases may suffice
