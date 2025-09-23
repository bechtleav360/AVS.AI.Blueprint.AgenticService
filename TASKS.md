awesome—here’s the updated blueprint checklist for a **single microservice** (FastAPI + Pydantic AI + Dapr/RabbitMQ + Dynaconf) that supports **both thin and fat events**, fetches **thin-event data via a Data Gateway**, and implements a **chain-of-responsibility** style where the agent listens to multiple topics and self-selects whether to act.

---

# Microservice Blueprint (Thin & Fat Events + Data Gateway + Chain of Responsibility)

## 1) Repository & Folder Structure

```
asset-backup-checker/
├─ src/
│  ├─ api/
│  │  ├─ __init__.py
│  │  ├─ routes.py              # FastAPI routers: /check-backup, /events/*, /actuators/*
│  │  └─ deps.py                # DI providers (dynaconf settings, clients)
│  ├─ agent/
│  │  ├─ __init__.py
│  │  ├─ logic.py               # pure heuristics (“cloud backup?”)
│  │  ├─ tools.py               # side-effecting helpers (DNS, CMDB, cloud calls)
│  │  ├─ runtime.py             # Pydantic AI agent assembly + run_check()
│  │  └─ decision.py            # chain-of-responsibility predicates & routing
│  ├─ models/
│  │  ├─ __init__.py
│  │  ├─ asset.py               # AssetMetadata
│  │  ├─ result.py              # AgentOutput
│  │  └─ events.py              # EventEnvelopeThin, EventEnvelopeFat, enums
│  ├─ gateways/
│  │  ├─ __init__.py
│  │  └─ data_gateway.py        # client to fetch full asset by ID for thin events
│  ├─ app.py                    # FastAPI app, router include, telemetry init
│  ├─ config.py                 # Dynaconf settings loader
│  ├─ telemetry.py              # OpenTelemetry init & ASGI middleware
│  └─ __init__.py
├─ dapr/
│  └─ components/
│     └─ rabbitmq-pubsub.yaml   # Dapr pubsub (RabbitMQ), secrets via env/secret store
├─ .dapr/
│  └─ config.yaml               # local tracing/logging config
├─ settings.toml                # Dynaconf base config (no secrets)
├─ .env.example                 # sample env for local dev
├─ tests/
│  ├─ unit/
│  │  ├─ test_logic.py
│  │  ├─ test_decision.py
│  │  └─ test_models.py
│  └─ integration/
│     └─ test_pubsub_flow.py
├─ .dockerignore
├─ Dockerfile
├─ docker-compose.yml
├─ pyproject.toml               # black(120), ruff common, isort, pytest
├─ .pre-commit-config.yaml
├─ README.md
├─ CONTRIBUTING.md
└─ azure-pipelines.yml
```

---

## 2) Event Model (support THIN & FAT)

### 2.1 Envelopes (in `models/events.py`)

* **Common envelope fields (both types):**

  * `event_id` (UUID, idempotency), `event_type` (e.g., `asset.metadata.updated`),
    `schema_version`, `occurred_at` (UTC ISO), `correlation_id`, `causation_id`,
    `traceparent` (W3C), `tenant_id`.
* **THIN event** (`EventEnvelopeThin`):

  * `data`: `{ "asset_id": str, "summary": { optional minimal fields } }`
  * `links`: `{ "asset_url": str | None }` (pointer to gateway/CMDB)
  * Contract: **no full asset**; consumers must fetch via **Data Gateway**.
* **FAT event** (`EventEnvelopeFat`):

  * `data`: `{ "asset": AssetMetadata }` (immutable snapshot)
  * Size guardrails: strip secrets, keep ≤ \~256 KB.

### 2.2 Topic & Versioning

* Topics (examples):

  * `assets.metadata` (thin/fat updates), `assets.created`, `assets.backup.config.changed`, `assets.results.backup-check`.
* Include `schema_version` in the envelope; consumers branch on version.

---

## 3) Chain of Responsibility (CoR) Design

### 3.1 Multi-topic Listener

* The service **subscribes to multiple topics** via Dapr (RabbitMQ), e.g.:

  * `/events/assets` handles `assets.metadata`, `assets.created`, `assets.backup.config.changed`.
* **Do not** pre-filter at the broker; every agent **decides locally** whether to act.

### 3.2 Decision Engine (in `agent/decision.py`)

* Provide a **registry** of handlers:

  * Each handler: `predicate(envelope) -> bool` + `action(envelope) -> AgentOutput | None`.
* Order: **lightweight predicates first** (cheap checks), then heavier ones.
* Examples:

  * `is_relevant_asset_type(envelope)` (db/vm/bucket/fs)
  * `has_backup_signals(envelope)` (URIs/tags present)
  * `is_duplicate(event_id)` (idempotency cache)
* If **no predicate matches** → **ack & ignore** (this *is* the CoR “pass along”).

### 3.3 Idempotency & Correlation

* Maintain a **dedup store** keyed by `event_id` (in-memory with TTL for local, Redis/DB in prod).
* Propagate `correlation_id`/`traceparent` to any published results.

---

## 4) Thin vs Fat Event Handling

### 4.1 Thin Event Flow

1. Parse `EventEnvelopeThin`.
2. Validate `tenant_id`, `schema_version`, `event_type`.
3. **Fetch full asset** via `gateways.data_gateway.get_asset(asset_id)`:

   * Retries with backoff & timeouts.
   * Return `AssetMetadata`.
4. Run `decision` predicates; if relevant → `agent.runtime.run_check(asset)`.
5. Publish result (thin) to `assets.results.backup-check` (include decision, evidence).

### 4.2 Fat Event Flow

1. Parse `EventEnvelopeFat` → extract `AssetMetadata`.
2. Run `decision` predicates directly (no fetch).
3. If relevant → `agent.runtime.run_check(asset)`.
4. Publish result (thin) to `assets.results.backup-check`.

### 4.3 Error Policy

* Gateway failures on thin events:

  * Distinguish **transient** (retry with DLQ after N attempts) vs **permanent** (schema/404 → ack & log).
* Poison messages:

  * Use Dapr/RabbitMQ DLQ; include envelope + error summary; never drop silently.

---

## 5) FastAPI Endpoints (Spring-style actuators)

* `POST /check-backup` → body: `AssetMetadata` → returns `AgentOutput`.
* `POST /events/assets` → body: `EventEnvelopeThin | EventEnvelopeFat` → runs CoR + agent as above.
* Actuators:

  * `GET /actuators/health` (aggregate: app ready + downstream summaries)
  * `GET /actuators/livez`
  * `GET /actuators/readyz` (optionally ping gateway/Dapr)

---

## 6) Dapr + RabbitMQ (pub/sub)

* `dapr/components/rabbitmq-pubsub.yaml`: `type: pubsub.rabbitmq`, `connectionString` via env/secret.
* Subscriptions: YAML or programmatic to bind topics (above) → `route: /events/assets`.
* Publishing helper (SDK/HTTP) for `assets.results.backup-check`.

---

## 7) Data Gateway Client (in `gateways/data_gateway.py`)

* Config from Dynaconf: `DATA_GATEWAY_BASE_URL`, auth, timeouts.
* `async def get_asset(asset_id: str) -> AssetMetadata`

  * HTTP GET `/assets/{id}` (or GraphQL), map response → `AssetMetadata`.
  * Enforce **timeouts, retries, circuit breaker** (simple token bucket/CB).
  * Add tracing headers (`traceparent`) for OTel continuity.

---

## 8) Pydantic AI Agent

* `agent/logic.py`: **pure** functions:

  * `detect_cloud_provider(provider, tags, uri) -> (provider|None, evidence:list[str])`
  * `score_cloud_backup(asset) -> (bool, confidence:float, evidence:list[str])`
* `agent/tools.py`: optional side-effect tools (DNS/CMDB/cloud calls).
* `agent/runtime.py`:

  * Compose agent (prompt + tools).
  * `async def run_check(asset: AssetMetadata) -> AgentOutput`.

---

## 9) Config (Dynaconf)

* `settings.toml` + env overrides:

  * `APP_NAME`, `APP_PORT`, `ENV_FOR_DYNACONF`
  * `DAPR_PUBSUB_NAME="rabbitmq-pubsub"`
  * `DATA_GATEWAY_BASE_URL`, `DATA_GATEWAY_TIMEOUT_S`, `RETRY_MAX_ATTEMPTS`
  * `OTEL_EXPORTER_OTLP_ENDPOINT`, `LOG_LEVEL`
* `config.py`: `settings = Dynaconf(...)`.
* Never hard-code secrets; use env/Secret store.

---

## 10) Observability (OpenTelemetry)

* `telemetry.py`:

  * Tracer provider + OTLP exporter if configured.
  * ASGI middleware; inject/extract W3C context.
* Spans & attributes:

  * Root span per request; child spans for **gateway fetch**, **agent run**, **publishes**.
  * Attributes: `asset_id`, `event_type`, `envelope_type` (`thin`/`fat`).

---

## 11) Docker & Compose

* Dockerfile: multi-stage, `python:3.11-slim`, non-root, `uvicorn app:app`.
* `.dockerignore`: venv/caches/tests/etc.
* `docker-compose.yml`:

  * `app` + `rabbitmq` (`:5672`, `:15672`), optional `daprd` sidecar (or use Dapr CLI).
  * Mount `./dapr/components`.

---

## 12) Linting, Tests, CI

* **Linting (reasonable)**:

  * Black `line-length = 140`, Ruff (common rules), Isort (black profile), optional mypy (basic).
* **Tests**:

  * Unit: `logic`, `decision` (predicates), models.
  * Integration: thin & fat flows; gateway mocked; pub/sub route.
  * Idempotency & DLQ scenarios.
* **Azure Pipelines**:

  * Jobs: lint → tests → docker build (optional push).

---

## 13) CONTRIBUTING.md (key rules)

* **Layering**:

  * `api` (transport), `agent.logic` (pure), `agent.tools` (IO), `agent.runtime` (agent),
    `agent.decision` (CoR predicates), `gateways` (external calls), `models` (schemas).
* **CoR contract**:

  * Handlers must be **cheap to evaluate**; only one handler may own final action per event (document precedence).
  * If not relevant, **ack & return** quickly.
* **Thin vs Fat**:

  * Thin **must** fetch via `gateways.data_gateway`; **never** bypass.
  * Fat **must** be treated as immutable snapshot; never mutate, never echo secrets.
* **Idempotency**:

  * All handlers must check & set `event_id` in dedup store before acting.
* **Observability & Security**:

  * Include `asset_id` in logs (no PII); propagate `traceparent`.
  * No secrets in logs/events/results.
* **Style**:

  * Black(120), Ruff common, pre-commit required; pragmatic, not pedantic.

---

## 14) Acceptance Criteria

* Subscribes to multiple topics; **self-selects** relevant events via predicates (CoR).
* Handles **THIN** (fetches via Data Gateway) and **FAT** events correctly.
* Produces `AgentOutput` and publishes a **thin result event**.
* Idempotent processing; DLQ on poison messages.
* Actuators under `/actuators/*`; OTel traces across fetch/agent/publish.
* Pre-commit/CI pass; minimal Docker; README/CONTRIBUTING updated.

---

### Design Notes

* Prefer **thin as default** but ensure fat path is first-class for snapshot/audit needs.
* Keep events small; if fat exceeds safe size, publish **link to snapshot** instead.
* CoR keeps agents decoupled: many agents can listen to the same topics and **independently** decide to act—no central orchestrator.
