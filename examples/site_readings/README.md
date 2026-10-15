# Site Readings -- named connections

One agent consumes the same subject (`readings.>`) from two sites, each with its own NATS account,
over two **named connections** supplied by a **connection source**. The agent's code never learns
that there are sites: the source decides which connections exist, how each one is consumed, which
deliveries may run, and what each run sees.

A reading above its site's threshold is stored as an alert; one within it is skipped
(`HandlerResult.skipped`). `GET /api/alerts` lists the alerts.

## What the source does

`src/connections.py` (named by `nats_connection_source` in `settings.toml`):

| Hook | Here |
|---|---|
| `claims(agent, subjects)` | Every declared subject under `readings.` belongs to the sites -- so none of them is ever consumed on the agent's default connection, even before a site exists. |
| `connections()` | `site_a` and `site_b`, each logging in as its own account's agent user (`example_sites` in `settings.toml`; the password from `EXAMPLE_NATS_PASSWORD`). |
| `binding(agent, subjects, connection)` | The site's durable consumer: subject prefix `site.<name>.` (wire subject `site.site_a.readings.recorded`, the handler sees `readings.recorded`), stream `READINGS_<NAME>`, deliver subject `deliver.<name>.<agent>`. Bind-only: the consumer is the deployment's (`deploy/provision.py`). |
| `validate(connection, subject, event)` | A delivery runs only if the wire subject and the event's `source` (`/sites/<name>`) both name the connection's site; anything else is terminated before a handler sees it. |
| `run_scope(connection)` | Opens the site's settings (`src/sites.py`) around the run, so the service applies that site's threshold. Each run starts in an empty context: a run sees its own site only. |

The agent itself is the usual shape: `ReadingHandler` routes `reading.recorded`, extracts the
`ReadingRecorded` DTO and calls `ReadingService.on_reading()` once; the service decides.

## Running

```bash
export EXAMPLE_NATS_PASSWORD=<any local value>      # the broker and the agent read the same variable
export DYNACONF_NATS_PASSWORD="$EXAMPLE_NATS_PASSWORD"
docker compose -f deploy/docker-compose.yml up -d   # broker with accounts PROC, SITE_A, SITE_B on :4224
python deploy/provision.py                          # streams and consumers, as each site's admin
uvicorn src.main:create_app --factory --port 8000
python deploy/provision.py --publish                # one reading below, one above each threshold
curl localhost:8000/api/alerts                       # site_a 51.0 (threshold 50), site_b 81.0 (threshold 80)
docker compose -f deploy/docker-compose.yml down
```

`/health/ready` stays 503 until both site connections are bound (`nats_connections_readiness = "all"`).
The process account (`proc`) may neither publish nor subscribe: the agent's default connection is
opened but carries no subject, which is what `claims` guarantees.

## Project structure

```
site_readings/
  settings.toml            # nats_connection_source, the sites, readiness
  src/
    main.py                # declaration + create_app()
    connections.py         # the ConnectionSource (deployment side)
    sites.py               # per-run site settings, set by run_scope
    handlers/reading_handler.py
    services/reading_service.py
    models/dto.py            # DTO: ReadingRecorded
    models/domain_models.py  # Reading, Alert
    api/routes.py          # GET /api/alerts
  deploy/
    nats-accounts.conf     # the example broker: one account per site, passwords from the environment
    docker-compose.yml
    provision.py           # what the deployment owns: streams and consumers
  tests/
```

## Tests

```bash
pytest tests
```

The tests need no broker: they check the source's answers (connections, claims, bindings,
validation, run scope isolation) and the handler/service split.
