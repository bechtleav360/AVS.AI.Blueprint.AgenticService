# Health checks

Readiness is computed from registered health checks, per agent, and cached. This directory holds
the pieces; `ActuatorApi` wires them and serves `/health/live` and `/health/ready`.

## Writing a check

Subclass `HealthCheckerBase` and return a `ComponentHealth`:

```python
from blueprint.agents.io.api.actuators.health import HealthCheckerBase
from blueprint.agents.models.api import ComponentHealth


class DatabaseHealthChecker(HealthCheckerBase):
    async def health_check(self) -> ComponentHealth:
        ok = await ping_database()
        return ComponentHealth(status="healthy" if ok else "unhealthy", message="database reachable" if ok else "no answer")
```

**The status of a component is `"healthy"` or `"unhealthy"`.** Anything other than `"healthy"`
counts as failing -- `"UP"` included, which the payload uses for agents and the pod, not for
components. A check that raises counts as unhealthy.

Register it on the builder, inside the agent it belongs to:

```python
AppBuilder().with_health_checker("db", DatabaseHealthChecker())
```

In a group, two agents may both register `"db"`; they appear as `orders.db` and `billing.db`.

## What is here

| Module | Purpose |
|---|---|
| `health_base.py` | `HealthCheckerBase`, and `HealthCheckEntry` -- a check with the agent it belongs to, carried as data. |
| `client_health.py` | `ClientHealthChecker`, registered by the framework for every transport client. It calls `connect()` before each check. |
| `cache_health.py` | `CacheHealthChecker`, registered for every named cache. |
| `sessions_health.py` | `SessionsServiceHealthChecker`, a heartbeat-age check for the sessions bus. Not registered by the framework. |
| `health_cache.py` | `HealthCheckCache`: runs the checks every `health_check_interval_seconds`, reduces them to one verdict per agent, applies the readiness policy and tells the supervisor. `refresh()` recomputes at once. |
| `namespace_supervisor.py` | `NamespaceSupervisor`: per-agent up/down, the `blueprint.namespace.up` gauge and ERROR event (C7), pausing a degraded agent's consumption (C4), and the startup-failure latch. |
| `readiness_policy.py` | `ReadinessPolicy`: `all`, `critical` or `any` -- which degraded agents take the pod out of rotation (C3). |

The concepts -- what makes an agent degraded, what happens then, and how the policy decides -- are
documented for users in `src/blueprint/agent_generator/docs/concepts/observability.md`
(`asbs docs observability --cat`).
