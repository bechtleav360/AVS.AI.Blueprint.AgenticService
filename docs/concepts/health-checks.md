# Concept: Health Checks

Learn how to monitor service health and dependencies.

---

## What are Health Checks?

Health checks are endpoints that report whether your service is running and healthy. They're used by:
- **Load balancers** — Route traffic to healthy instances
- **Kubernetes** — Restart unhealthy pods
- **Monitoring** — Alert when service is down
- **Debugging** — Verify service is working

---

## Built-in Health Endpoint

The framework provides a default health check endpoint:

```bash
curl http://localhost:8000/health
```

**Response:**
```json
{
  "status": "ok"
}
```

---

## Health Check Levels

### Level 1: Basic Health

Service is running and responding:

```bash
curl http://localhost:8000/health
# Response: {"status": "ok"}
```

### Level 2: Dependency Health

Service and dependencies are healthy:

```bash
curl http://localhost:8000/health/dependencies
# Response: {
#   "status": "ok",
#   "database": "ok",
#   "cache": "ok",
#   "dapr": "ok"
# }
```

### Level 3: Detailed Health

Detailed information about service state:

```bash
curl http://localhost:8000/health/detailed
# Response: {
#   "status": "ok",
#   "uptime": 3600,
#   "requests_processed": 1234,
#   "errors": 0,
#   "cache_size": 42,
#   "database_connections": 5
# }
```

---

## Implement Custom Health Checks

### Check Database Connection

```python
from blueprint.agents import RestApi

class MyRestApi(RestApi):
    def _register_routes(self):
        @self.router.get("/health/db")
        async def check_database():
            try:
                # Test database connection
                result = await database.execute("SELECT 1")
                return {"status": "ok", "database": "connected"}
            except Exception as e:
                logger.error(f"Database health check failed: {e}")
                return {
                    "status": "error",
                    "database": "disconnected",
                    "error": str(e)
                }
```

### Check Cache Health

```python
@self.router.get("/health/cache")
async def check_cache():
    try:
        cache = self._registry.cache_service

        if not cache:
            return {"status": "ok", "cache": "disabled"}

        # Test cache operations
        test_key = "health_check"
        cache.set("health", test_key, {"test": True}, ttl=10)
        result = cache.get("health", test_key)

        if result:
            return {"status": "ok", "cache": "healthy"}
        else:
            return {"status": "error", "cache": "not responding"}

    except Exception as e:
        logger.error(f"Cache health check failed: {e}")
        return {"status": "error", "cache": "error", "error": str(e)}
```

### Check External Service

```python
@self.router.get("/health/external")
async def check_external_service():
    try:
        # Test connection to external API
        response = await external_api.health_check()

        if response.status_code == 200:
            return {"status": "ok", "external_api": "healthy"}
        else:
            return {
                "status": "error",
                "external_api": "unhealthy",
                "status_code": response.status_code
            }

    except Exception as e:
        logger.error(f"External service health check failed: {e}")
        return {"status": "error", "external_api": "unreachable"}
```

---

## Kubernetes Health Checks

### Liveness Probe

Checks if service is running. If it fails, Kubernetes restarts the pod.

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3
```

### Readiness Probe

Checks if service is ready to accept traffic. If it fails, Kubernetes removes the pod from load balancer.

```yaml
readinessProbe:
  httpGet:
    path: /health/dependencies
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 5
  timeoutSeconds: 3
  failureThreshold: 2
```

### Startup Probe

Checks if service has started. Gives service time to initialize.

```yaml
startupProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 0
  periodSeconds: 10
  timeoutSeconds: 3
  failureThreshold: 30  # 30 * 10 = 300 seconds max startup time
```

---

## Monitoring Health

### Prometheus Metrics

Export health metrics for monitoring:

```python
from prometheus_client import Counter, Gauge

health_checks = Counter("health_checks_total", "Total health checks")
healthy_services = Gauge("healthy_services", "Number of healthy services")


@self.router.get("/health/metrics")
async def health_metrics():
    health_checks.inc()

    healthy = 0

    # Check database
    try:
        await database.execute("SELECT 1")
        healthy += 1
    except:
        pass

    # Check cache
    if self._registry.has_cache():
        healthy += 1

    healthy_services.set(healthy)

    return {"healthy_services": healthy}
```

### Logging Health Status

```python
import logging

logger = logging.getLogger(__name__)


@self.router.get("/health/log")
async def health_with_logging():
    logger.info("Health check requested")

    try:
        # Check dependencies
        db_ok = await check_database()
        cache_ok = await check_cache()

        if db_ok and cache_ok:
            logger.info("All health checks passed")
            return {"status": "ok"}
        else:
            logger.warning("Some health checks failed")
            return {
                "status": "degraded",
                "database": "ok" if db_ok else "error",
                "cache": "ok" if cache_ok else "error"
            }

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "error"}
```

---

## Real-World Example

### Complete Health Check System

```python
from blueprint.agents import RestApi
from datetime import datetime


class HealthRestApi(RestApi):
    def _register_routes(self):
        @self.router.get("/health")
        async def basic_health():
            """Basic health check - service is running."""
            return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

        @self.router.get("/health/dependencies")
        async def dependency_health():
            """Check all dependencies."""
            results = {
                "status": "ok",
                "timestamp": datetime.utcnow().isoformat(),
                "checks": {}
            }

            # Check database
            try:
                await database.execute("SELECT 1")
                results["checks"]["database"] = "ok"
            except Exception as e:
                results["checks"]["database"] = f"error: {str(e)}"
                results["status"] = "degraded"

            # Check cache
            try:
                cache = self._component_registry.cache_service
                if cache:
                    test_key = cache.hash("health_check")
                    cache.set("health", test_key, {"test": True}, ttl=10)
                    results["checks"]["cache"] = "ok"
                else:
                    results["checks"]["cache"] = "disabled"
            except Exception as e:
                results["checks"]["cache"] = f"error: {str(e)}"
                results["status"] = "degraded"

            # Check Dapr
            try:
                response = await dapr_client.invoke_method(
                    app_id="test",
                    method_name="health"
                )
                results["checks"]["dapr"] = "ok"
            except Exception as e:
                results["checks"]["dapr"] = f"error: {str(e)}"
                results["status"] = "degraded"

            return results

        @self.router.get("/health/detailed")
        async def detailed_health():
            """Detailed health information."""
            cache = self._component_registry.cache_service

            return {
                "status": "ok",
                "timestamp": datetime.utcnow().isoformat(),
                "service": {
                    "name": "invoice-analyzer",
                    "version": "1.0.0",
                    "uptime_seconds": 3600
                },
                "resources": {
                    "cache_enabled": cache is not None,
                    "cache_size": cache.get_stats()["size"] if cache else 0,
                    "memory_mb": 256
                },
                "metrics": {
                    "requests_processed": 1234,
                    "errors": 5,
                    "error_rate": 0.004
                }
            }
```

---

## Best Practices

1. **Keep health checks fast** — < 100ms response time
2. **Don't log health checks** — They're called frequently
3. **Check critical dependencies** — Database, cache, external APIs
4. **Return meaningful status** — "ok", "degraded", "error"
5. **Include timestamps** — Know when check was run
6. **Monitor health endpoints** — Alert on failures
7. **Set appropriate timeouts** — Prevent hanging checks

---

## Common Patterns

### Graceful Degradation

```python
@self.router.get("/health")
async def health():
    status = "ok"
    checks = {}

    # Database is critical
    try:
        await database.execute("SELECT 1")
        checks["database"] = "ok"
    except:
        checks["database"] = "error"
        status = "error"  # Critical failure

    # Cache is optional
    try:
        cache = self._registry.cache_service
        if cache:
            checks["cache"] = "ok"
    except:
        checks["cache"] = "error"
        # Don't change status - cache is optional

    return {"status": status, "checks": checks}
```

### Startup Delay

```python
import time

class MyRestApi(RestApi):
    def __init__(self):
        super().__init__()
        self.start_time = time.time()

    def _register_routes(self):
        @self.router.get("/health")
        async def health():
            uptime = time.time() - self.start_time

            # Give service 30 seconds to start
            if uptime < 30:
                return {"status": "starting", "uptime_seconds": uptime}

            return {"status": "ok", "uptime_seconds": uptime}
```

### Circuit Breaker Health

```python
class CircuitBreakerHealth(RestApi):
    def _register_routes(self):
        @self.router.get("/health")
        async def health():
            service = self._component_registry.get_service("payment_service")

            if service.circuit_breaker_open:
                return {
                    "status": "degraded",
                    "message": "Payment service circuit breaker is open"
                }

            return {"status": "ok"}
```

---

## Troubleshooting

### Health Check Timeout

**Problem:** Health check endpoint times out.

**Solution:**
1. Reduce number of checks
2. Increase timeout in Kubernetes
3. Run checks asynchronously

### False Positives

**Problem:** Health check says "ok" but service is broken.

**Solution:**
1. Add more comprehensive checks
2. Check actual functionality, not just connectivity
3. Monitor error rates

### Health Check Spam

**Problem:** Health checks fill up logs.

**Solution:**
1. Don't log health checks
2. Use separate logger with WARNING level
3. Suppress httpx/httpcore logs

---

## Next Steps

- [Exception Handling](exception-handling.md) — Handle errors gracefully
- [Caching](caching.md) — Improve performance with caching
- [Deployment](../deployment.md) — Deploy to production
