# Health Monitor

A system health monitoring service built with the Blueprint Agents framework. Demonstrates scheduler-based periodic monitoring with multiple schedulers, a status dashboard via REST, and manual trigger support.

## What it demonstrates

- **SchedulerBase** subclasses with different crontab intervals (per-minute health checks, hourly reports)
- **Multiple schedulers** registered via `with_scheduler()` on a single AppBuilder
- **ServiceBase** subclass for health-check business logic with endpoint monitoring
- **RestApiBase** subclass exposing a status dashboard
- **Cache integration** for persisting check results across scheduler ticks
- **Manual triggering** via the auto-registered `POST /{name}/trigger` endpoints

## Setup

```bash
pip install -e .
```

## Running

Using the ASBS CLI:

```bash
asbs dev
```

Or directly with uvicorn:

```bash
uvicorn src.main:app --reload
```

The API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

## Example curl commands

**Get full uptime report (all endpoints):**

```bash
curl http://localhost:8000/status
```

**Get status for a single endpoint:**

```bash
curl http://localhost:8000/status/httpbin
```

**Manually trigger a health check cycle:**

```bash
curl -X POST http://localhost:8000/health_check_scheduler/trigger
```

**Manually trigger a report generation:**

```bash
curl -X POST http://localhost:8000/report_scheduler/trigger
```
