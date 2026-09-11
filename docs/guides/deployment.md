# Deployment Guide

Packaging, deploying and operating Blueprint Agents applications with Docker, Kubernetes and Helm.

Two things shape everything below, and both are recent:

- **A Deployment runs a *group*, not an agent.** One image contains every agent the platform has;
  which of them a given process hosts is injected at container start. Regrouping is an edit to a
  Deployment, not a rebuild. See [Multi-Agent Setup](multi-agent-setup.md) for the model; this guide
  is about running it.
- **More than one replica is now safe**, under conditions this guide states. Core NATS
  subscriptions join a queue group, JetStream consumers are durable and share a deliver group, every
  delivery is acknowledged, naked or terminated explicitly, a cron tick fires once across replicas
  in both scheduler modes, and event deduplication is available. What you have to decide is listed
  under [Running more than one replica](#running-more-than-one-replica).

> **The delivery behaviour is covered by unit tests against mocked transports and has not been
> exercised against a real broker.** Queue-group distribution across replicas, redelivery after
> `nats_ack_wait`, durable survival across reconnect and the shutdown drain are all specified and
> implemented; none of them has been watched happening on a live NATS server. Treat the first
> multi-replica deployment as the experiment it is.

---

## The image

A scaffolded project ships a multi-stage Dockerfile whose production stage is:

```dockerfile
FROM python:3.13-slim-bookworm AS final

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --chown=appuser:appuser src ./src
COPY --chown=appuser:appuser settings.toml ./
COPY --chown=appuser:appuser agents.toml ./

# The disk cache backend writes here and cannot create it itself: WORKDIR made /app root-owned.
RUN mkdir -p /app/.cache && chown -R appuser:appuser /app/.cache

ENV PYTHONPATH="/app/src" \
    DYNACONF_ENVIRONMENT="production" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER appuser

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health/live || exit 1

EXPOSE 8000

ENTRYPOINT ["python", "-m", "blueprint.agents.entrypoint"]
```

Three things about it are load-bearing:

- **`agents.toml` is copied in; the group file is not.** The map says what the image *contains*, and
  changes only when an agent is added or removed -- which is a rebuild anyway. Which agents a
  *process* runs is a deployment decision and arrives separately, so baking it would defeat the one
  property the whole model exists for.
- **The command is `python -m blueprint.agents.entrypoint`**, not `uvicorn src.main:app`. A
  scaffolded `src/main.py` declares an agent and builds nothing; the entry point resolves this
  process's group, builds it and serves it. A project that has not migrated keeps `uvicorn
  src.main:app` and keeps working.
- **`secrets.toml` is never copied in.** Mount it, or supply the values as environment variables.

### Building and running

```bash
docker build -t my-agents:latest .

# One agent, no group file
docker run -d -p 8000:8000 \
    -e BLUEPRINT_AGENTS=order \
    -e DYNACONF_MODEL_API_KEY="sk-..." \
    my-agents:latest

# A group from a mounted file
docker run -d -p 8000:8000 \
    -v ./deployment-groups.yaml:/app/deployment-groups.yaml:ro \
    -e BLUEPRINT_GROUP=checkout \
    my-agents:latest
```

With neither, the process **stops before binding its port** and prints which of the two is missing.
That is deliberate: a pod that passes its probes while one agent's queue silently backs up is a
worse failure than a pod that will not start.

---

## Choosing what a process runs

| Variable | Default | Meaning |
|---|---|---|
| `BLUEPRINT_GROUP` | -- | Which group in the file to run. Optional when the file declares exactly one |
| `BLUEPRINT_AGENTS` | -- | Comma-separated agent names, supplying the group with no file at all |
| `BLUEPRINT_CRITICAL_AGENTS` | -- | Comma-separated subset whose failure stops the process and gates readiness |
| `BLUEPRINT_GROUP_CONFIG` | `./deployment-groups.yaml` | Where the group file is |
| `BLUEPRINT_AGENT_MAP` | `./agents.toml` | Where the agent map is |

The environment **overrides the file key by key**, so one Deployment can change the agent list
without editing or duplicating a mounted file. Every resolved value is logged with the source it
came from, because "which agents did this pod actually start" is the first question asked of a group
that misbehaves.

These five are read before any `Config` exists -- group composition decides which agents get a
configuration view at all -- so they are plain environment variables with an explicit `BLUEPRINT_`
prefix, not Dynaconf settings. They are not readable from agent code.

**One Deployment per group.** A group file with three groups is three Deployments over one image,
each setting its own `BLUEPRINT_GROUP`. Splitting an agent out into its own pod is a fourth
Deployment and an edit to the file; nothing is rebuilt, and nothing on the broker changes.

---

## Kubernetes with Helm

### Chart structure

```
helm/
  Chart.yaml
  values.yaml
  templates/
    deployment.yaml
    service.yaml
    configmap.yaml
    groups-configmap.yaml
    cronjob.yaml        # only if an agent runs a scheduler in "event" mode
    hpa.yaml
```

### values.yaml

```yaml
group: checkout          # which group this Deployment runs
replicaCount: 2          # safe; see "Running more than one replica"

image:
  repository: myregistry.azurecr.io/my-agents
  tag: "1.2.3"
  pullPolicy: IfNotPresent

service:
  type: ClusterIP
  port: 80
  targetPort: 8000

dapr:
  enabled: false         # a group has one Dapr endpoint; see the note under scaling
  appId: "checkout"
  appPort: 8000
  logLevel: "info"

app:
  port: 8000
  logLevel: "info"

resources:
  requests:
    cpu: 250m
    memory: 512Mi
  limits:
    cpu: "1"
    memory: 1Gi         # a group's memory is the sum of its agents; see "Sizing a group"

probes:
  liveness:
    path: /health/live
    initialDelaySeconds: 15
    periodSeconds: 20
    timeoutSeconds: 5
    failureThreshold: 3
  readiness:
    path: /health/ready
    initialDelaySeconds: 10
    periodSeconds: 10
    timeoutSeconds: 5
    failureThreshold: 12   # the broker's own startup; see "Health probes"

autoscaling:
  enabled: false
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
```

### Deployment template

```yaml
# templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}-{{ .Values.group }}
  labels:
    app: {{ .Release.Name }}
    group: {{ .Values.group }}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      app: {{ .Release.Name }}
      group: {{ .Values.group }}
  template:
    metadata:
      labels:
        app: {{ .Release.Name }}
        group: {{ .Values.group }}
      annotations:
        {{- if .Values.dapr.enabled }}
        dapr.io/enabled: "true"
        dapr.io/app-id: {{ .Values.dapr.appId | quote }}
        dapr.io/app-port: {{ .Values.dapr.appPort | quote }}
        dapr.io/log-level: {{ .Values.dapr.logLevel | quote }}
        {{- end }}
    spec:
      containers:
        - name: agents
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          ports:
            - containerPort: {{ .Values.app.port }}
          env:
            - name: BLUEPRINT_GROUP
              value: {{ .Values.group | quote }}
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
          envFrom:
            - configMapRef:
                name: {{ .Release.Name }}-config
            - secretRef:
                name: {{ .Release.Name }}-secrets
                optional: true
          volumeMounts:
            - name: groups
              mountPath: /app/deployment-groups.yaml
              subPath: deployment-groups.yaml
              readOnly: true
          livenessProbe:
            httpGet:
              path: {{ .Values.probes.liveness.path }}
              port: {{ .Values.app.port }}
            initialDelaySeconds: {{ .Values.probes.liveness.initialDelaySeconds }}
            periodSeconds: {{ .Values.probes.liveness.periodSeconds }}
            failureThreshold: {{ .Values.probes.liveness.failureThreshold }}
          readinessProbe:
            httpGet:
              path: {{ .Values.probes.readiness.path }}
              port: {{ .Values.app.port }}
            initialDelaySeconds: {{ .Values.probes.readiness.initialDelaySeconds }}
            periodSeconds: {{ .Values.probes.readiness.periodSeconds }}
            failureThreshold: {{ .Values.probes.readiness.failureThreshold }}
          resources:
            {{- toYaml .Values.resources | nindent 12 }}
      volumes:
        - name: groups
          configMap:
            name: {{ .Release.Name }}-groups
```

`POD_NAME` is worth injecting: the framework reads it for the telemetry `service.instance.id` and
for the NATS connection name (`<agent>.<group>.<pod>`), which is what makes "which replica did
that" answerable from the broker's own connection list.

### The group file as a ConfigMap

```yaml
# templates/groups-configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ .Release.Name }}-groups
data:
  deployment-groups.yaml: |
    groups:
      - name: checkout
        agents: [order, billing]
        critical_agents: [order]
      - name: reporting
        agents: [reports]
```

One ConfigMap, mounted into every Deployment; each picks its slice with `BLUEPRINT_GROUP`. The
alternative -- `BLUEPRINT_AGENTS` per Deployment and no file at all -- works and is simpler for two
or three agents; the file earns its keep once the composition is something you want to review as a
diff.

`critical_agents` decides two things at once: whether the process starts at all when that agent
cannot be loaded, and whether that agent can take the pod out of service rotation. The default is
**critical** for every agent in the group. Naming a subset is the deliberate choice to run the rest
without the others.

### Deploying

```bash
helm install checkout ./helm --namespace agents --create-namespace \
    --set group=checkout --set image.tag=1.2.3

helm upgrade checkout ./helm --namespace agents --set image.tag=1.3.0

# Split an agent out of the group: edit the group file, deploy a second release
helm install reporting ./helm --namespace agents --set group=reporting
```

---

## Running more than one replica

Three mechanisms make this safe, and each has a setting you should look at.

### 1. Every replica joins one queue group

Core NATS subscriptions carry a queue group and JetStream consumers are durable with a shared
deliver group, so **one message goes to one replica**. The name is the agent's namespace in a group,
and `nats_queue_group` (falling back to `app_name`) at the root -- never the deployment group, so
scaling out and regrouping are independent of each other.

### 2. Every delivery is acknowledged, naked or terminated

| Outcome | Disposition |
|---|---|
| Handled, or no handler matched it | **ack** -- an unmatched event is not a failure |
| A retryable failure | **nak**, redelivered after `nats_ack_wait` |
| A poison payload, or a `CriticalHandlerError` | **term**, and dead-lettered |
| `nats_max_deliver` attempts exhausted | dead-lettered |

Two keys to set deliberately:

- **`nats_ack_wait`** (default `300.0` seconds) must exceed your p99 handler duration. Set it below
  that and the broker redelivers work that is still in progress, to a second replica.
- **`nats_max_ack_pending`** (default `16`) is the in-flight limit **across every replica sharing
  the consumer**, not per replica. Scaling to eight replicas with the default gives you sixteen
  concurrent messages in total, which is usually the reason throughput does not improve with pod
  count.

### 3. Deduplication, if your handlers need it

Delivery is at-least-once, permanently: a lost acknowledgement, a pod killed mid-handler or a
rolling deploy each produce a redelivery *after* the first attempt has committed its side effects.
Two honest answers, and the framework will not choose for you:

- make the handlers safe to repeat (upsert rather than insert, key the outbound call on
  `event.id`), or
- set `idempotency_enabled = true` and `idempotency_ttl`.

**The TTL must outlast the broker's redelivery window**, which is
`nats_ack_wait * nats_max_deliver`:

```
300 s x 5 = 1500 s     # the defaults
idempotency_ttl = 1800 # with headroom for clock skew and a slow restart
```

Too short and a redelivery arrives after the marker has expired, which is the case dedup exists to
prevent. Too long only costs cache entries. If you raise `nats_ack_wait` or `nats_max_deliver`,
raise this with them.

Two limits to know: dedup needs the agent to declare `with_cache()` -- the marker lives in that
agent's own cache -- and `exists`-then-`set` is not atomic on either backend, so two replicas handed
the same event in the same instant can both dispatch. It closes the ordinary window, not every
window.

**Grouped Dapr is the exception that wants dedup on.** A group has one Dapr endpoint: it publishes
the union of every agent's topics and fans each delivery out to the agents that declared it, and the
single acknowledgement Dapr gets is their combination. So a retry asked for by one agent redelivers
to *every* agent in the group. NATS has no such coupling -- each agent holds its own subscription.

### Dead letters accumulate, and nothing drains them

A message that exhausts `nats_max_deliver`, or that a handler terminates, is published to
`nats_dead_letter_subject` -- by default `<queue group>.dead-letter`. The framework does not read
that subject. Messages sit there subject to the stream's retention, so **a deployment that never
drains it loses dead letters silently when the stream ages them out.**

Before going multi-replica, decide who reads it. `blueprint.events.dead_lettered` (labelled with
`reason` and whether the payload was `kept`) is the metric to alert on; the subject itself needs a
consumer -- an operational tool, a second agent, or a person with `nats sub`.

### Autoscaling

```yaml
# templates/hpa.yaml
{{- if .Values.autoscaling.enabled }}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {{ .Release.Name }}-{{ .Values.group }}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {{ .Release.Name }}-{{ .Values.group }}
  minReplicas: {{ .Values.autoscaling.minReplicas }}
  maxReplicas: {{ .Values.autoscaling.maxReplicas }}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: {{ .Values.autoscaling.targetCPUUtilizationPercentage }}
{{- end }}
```

CPU is a poor signal for an event-driven agent that spends its time waiting on an LLM. Consumer lag
or in-flight count is the metric you actually want to scale on, and reaching it needs a metrics
adapter. Raise `nats_max_ack_pending` before adding replicas: with the default, more pods share the
same sixteen in-flight messages.

---

## Schedulers

`scheduler_mode` has no default and is required as soon as a scheduler is registered, because
neither value is safe to inherit. It resolves **per agent**, so one agent may run an in-process
timer beside a neighbour driven by external ticks.

### `scheduler_mode = "in_process"`

An APScheduler timer runs in every replica, and each tick is **claimed** in the agent's own cache --
a marker keyed on `(scheduler, minute)` -- so the replica that stores it runs the tick and the rest
do not. Nothing is elected and nothing is held, so there is no lease to renew and none to be left
behind by a replica that dies.

It needs `.with_cache()` on that agent. Without one the claim has nowhere to go and **every replica
runs every tick**; the framework logs this at startup and `asbs validate` reports it. Right for local
development, plain Docker, and a single-replica deployment.

### `scheduler_mode = "event"`

No timer runs in the process at all. The tick arrives as an ordinary event on

```
<agent>.scheduler.<scheduler name>
```

-- the agent's namespace, or `app_name` for a scheduler at the root. It is the queue group that
delivers it, so exactly one replica runs it however many there are. It needs `event_bus` set.

**Nothing in this repository generates the `CronJob`.** The schedule stays declared in agent code,
the `CronJob` must publish on the schedule that code declares, and keeping them in step is currently
manual:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: order-nightly-tick
spec:
  schedule: "0 2 * * *"          # must match the scheduler's declared crontab
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: tick
              image: natsio/nats-box:latest
              args:
                - /bin/sh
                - -c
                - |
                  nats --server "$NATS_URL" pub order.scheduler.nightly \
                    '{"specversion":"1.0","type":"scheduler.tick","source":"cronjob","id":"'"$(date +%s)"'"}'
              env:
                - name: NATS_URL
                  value: nats://nats:4222
```

The tick handler matches on the **topic**, not the event type, so any CloudEvent published to that
subject fires the scheduler. A `CronJob` is at-least-once too -- a restart or a missed
`startingDeadlineSeconds` can produce a second tick -- so an event-mode scheduler whose tick is not
safe to repeat wants `idempotency_enabled`.

Both modes are alerted on the same way: `blueprint.scheduler.tick_age_seconds` reports how long ago
the last tick ran, `-1` before the first. "Two intervals late" is an expression you write against
that gauge; the framework does not interpret your crontab.

---

## Health probes

Two endpoints, and they answer different questions:

| Endpoint | Question | Never depends on |
|---|---|---|
| `GET /health/live` | Is this process running? | any agent's state |
| `GET /health/ready` | Should this pod receive traffic? | -- |

**Liveness is never agent-dependent, deliberately.** If one degraded agent failed the pod's liveness
probe, Kubernetes would restart every agent in the group, reintroducing exactly the blast radius
grouping was paid to remove.

Also served, and useful when debugging rather than as probes: `GET /info`, `/status/env`,
`/status/llm`, `/status/build`. There is no `/health/detailed`.

### `readiness_policy`

A process-scope key -- one pod has one readiness probe:

| Value | `/health/ready` is `200` when |
|---|---|
| `all` (default) | every agent is up |
| `critical` | every agent the group flagged critical is up |
| `any` | at least one agent is up |

The root namespace gates readiness under all three: it holds the shared infrastructure, and a
single-agent application is entirely root.

### The payload

```json
{
  "status": "UP",
  "policy": "critical",
  "components": {
    "orders.nats_client": {"status": "healthy", "message": "Connected to NATS server at ..."},
    "billing.cache": {"status": "unhealthy", "message": "redis is unreachable"}
  },
  "namespaces": {
    "<root>":  {"status": "UP",   "critical": true,  "failing": []},
    "orders":  {"status": "UP",   "critical": true,  "failing": []},
    "billing": {"status": "DOWN", "critical": false, "failing": ["billing.cache"]}
  }
}
```

`components` is keyed by entry name -- bare at the root, `<agent>.<name>` for an agent -- so a
single-agent payload's keys are unchanged. `namespaces` exists because the policy makes `status` no
longer derivable from `components`: the pod above answers `UP` with a failing check in it.

### Broker startup

The broker connection is established asynchronously after startup, and `/health/ready` answers `503`
until every topic subscription is active. Set `failureThreshold` high enough to outlast the broker's
own startup -- `periodSeconds: 10` with `failureThreshold: 12` gives two minutes. See
[Broker Startup Resilience](../concepts/event-processing.md#broker-startup-resilience).

### Alerting on an agent, not on the pod

Grouping removes the pod restart that used to serve as the alert, so the alert is emitted
deliberately instead. Every path that stops an agent serving emits an ERROR-level event carrying
that agent's own telemetry identity and drives `blueprint.namespace.up{agent} = 0` -- including the
case the probe cannot see, an agent whose subscriptions have gone while the process stays healthy.
Alert on that gauge. The probe decides where traffic goes; alerting decides who is woken.

A degraded agent's transports are **paused**, not closed: it stops consuming, and can be seen to
recover. A closed client would report itself unhealthy for ever, so a transient fault would take the
agent off its topics permanently.

---

## Writable cache directory

The disk cache backend (`cache.backend = "disk"`, the default) writes to `cache.cache_dir`, which
defaults to the **relative** path `.cache/blueprint` -- resolved against the working directory, so
`/app/.cache/blueprint` in the generated image. It is created at startup, and a container can only
create it where the process user may write.

Two things have to be true, and neither is automatic:

1. **The directory belongs to the user the process runs as.** `WORKDIR /app` creates `/app` owned by
   root, and the image runs as `appuser`, so `mkdir /app/.cache` fails with EACCES. The generated
   Dockerfile therefore creates and hands it over at build time:

   ```dockerfile
   RUN mkdir -p /app/.cache && chown -R appuser:appuser /app/.cache
   ```

   A project scaffolded before this was added needs the same two lines.

2. **A read-only root filesystem needs a volume mounted there.** With `readOnlyRootFilesystem: true`
   the ownership above is irrelevant -- nothing may be written anywhere except a mounted volume, and
   the mount is declared in the pod spec rather than discovered at runtime:

   ```yaml
   spec:
     containers:
       - name: agents
         securityContext:
           readOnlyRootFilesystem: true
           runAsNonRoot: true
         volumeMounts:
           - name: cache
             mountPath: /app/.cache
     volumes:
       - name: cache
         emptyDir:
           sizeLimit: 1Gi
   ```

   Keep `sizeLimit` at or above `cache.size_limit` (default 1 GB): an `emptyDir` is backed by node
   disk, and a pod that exceeds its limit is evicted.

If the directory cannot be created the service fails at startup with a message naming the path and
these options, rather than an errno from inside a constructor.

**Grouped agents still need only one mount.** Each agent's cache is a *subdirectory* of
`cache.cache_dir` -- `<cache_dir>/orders.default` for agent `orders`, and
`<cache_dir>/orders.sessions` for a cache it named `sessions` -- so a group of five agents mounts the
one volume a single agent does. One `size_limit` budget covers all of them, which is worth
remembering when the group grows.

**Or avoid the filesystem entirely.** `cache.backend = "redis"` needs no writable path, which makes
it the simpler choice for a hardened pod, and the only choice if the cache has to survive a restart
or be shared across replicas -- an `emptyDir` is per pod and is deleted with it. On Redis the
per-agent separation is a key prefix (`<key_prefix>:orders.default`) rather than a directory.

> **Upgrading an existing deployment starts with a cold cache.** The key layout changed during the
> multi-agent work, so a persistent Redis cache or a mounted disk cache will not find its old
> entries. Nothing errors; the first requests after the deploy are slow. If any cache entry is
> load-bearing rather than an optimisation, migrate it before cutting over.

---

## Configuration

### Environment variable overrides

Any setting can be overridden at runtime with an environment variable. The default prefix is
`DYNACONF_`, and **`__` denotes nesting** -- so a top-level key takes a single underscore and a
sectioned one takes two:

```toml
[default]
app_port = 8000
log_level = "INFO"
model_provider = "openai"

[default.cache]
backend = "redis"

[default.runtimes.order_agent]
model_name = "gpt-4.1-nano"
```

```bash
docker run \
    -e DYNACONF_APP_PORT=9000 \
    -e DYNACONF_LOG_LEVEL="DEBUG" \
    -e DYNACONF_MODEL_PROVIDER="openai" \
    -e DYNACONF_MODEL_API_KEY="sk-..." \
    -e DYNACONF_CACHE__BACKEND="redis" \
    -e DYNACONF_RUNTIMES__ORDER_AGENT__MODEL_NAME="gpt-4.1-mini" \
    my-agents:latest
```

Getting this wrong is quiet: `DYNACONF_APP__PORT` creates a nested `app.port` that nothing reads,
and the process keeps its default. Most of the framework's own keys are **flat** -- `app_port`,
`log_level`, `log_format`, `event_bus`, `nats_url`, `model_provider`, `idempotency_enabled`,
`scheduler_mode`, `readiness_policy`. The sectioned ones are `cache.*` and `runtimes.<name>.*`.

#### Choosing your own prefix

`DYNACONF_` is the default, not the only option. Declare `envvar_prefix` as a **top-level** key --
above every section, because the prefix is resolved before any environment section is selected:

```toml
envvar_prefix = "ORDERS"

[default]
app_name = "orders"
```

```bash
docker run -e ORDERS_MODEL_NAME="gpt-4" my-agents:latest
```

An operator can override the declared prefix without rebuilding the image, using the framework's own
bootstrap variable:

```bash
docker run -e BLUEPRINT_ENVVAR_PREFIX="ORDERS" -e ORDERS_MODEL_NAME="gpt-4" my-agents:latest
```

Three rules the service enforces at startup, each failing loudly rather than being ignored:

| Declaration | Result |
|---|---|
| `envvar_prefix = "orders"` | **Rejected.** Dynaconf upper-cases the prefix before matching, so the `orders_*` you export would never be read. Declare it in the case you will export it in. |
| `envvar_prefix = "BLUEPRINT"` or `"POD"` | **Rejected.** Stripping the prefix would turn `BLUEPRINT_GROUP` into the key `group` and expose deployment identity to agent code. |
| `envvar_prefix` inside `[default]` | **Rejected.** The prefix decides how the environment section is chosen, so it cannot live inside one. |

`DYNACONF_*` keeps working whatever prefix you declare -- Dynaconf always loads it and cannot be told
not to -- so an existing deployment can migrate one variable at a time. Where both spellings set the
same key, the declared prefix wins.

`envvar_prefix` is **process scope**: one process reads its environment through one prefix, so an
agent's own settings file cannot set it. The same is true of `app_port`, `app_host`, `app_workers`,
`app_environment`, `event_bus`, `log_level`, `log_format`, `readiness_policy` and
`nats_stream_name` -- they belong to the group's settings file, and a copy under one agent's scope
is dropped with a warning at startup.

#### Turning the prefix off

`envvar_prefix = false` (or `BLUEPRINT_ENVVAR_PREFIX=false`) makes every environment variable a
setting, with no prefix at all:

```bash
docker run -e BLUEPRINT_ENVVAR_PREFIX=false -e MODEL_NAME="gpt-4" my-agents:latest
```

**This absorbs the whole process environment into your configuration** -- `PATH`, `HOSTNAME`, the
service-discovery variables Kubernetes injects for every Service in the namespace, and any credential
that happens to be exported. Measured on a development machine: 88 settings keys from a 5-key
settings file. Anything colliding with one of your key names silently replaces it.

Prefer a short project prefix. Use `false` only for a container whose environment you fully control
and deliberately want to pass through -- and read the startup log line, which states which prefix the
process resolved.

### ConfigMap and Secret

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: checkout-config
data:
  DYNACONF_APP_PORT: "8000"
  DYNACONF_LOG_LEVEL: "info"
  DYNACONF_EVENT_BUS: "nats"
  DYNACONF_NATS_URL: "nats://nats:4222"
  DYNACONF_CACHE__BACKEND: "redis"
  DYNACONF_CACHE__REDIS_URL: "redis://redis:6379"
  DYNACONF_IDEMPOTENCY_ENABLED: "true"
  DYNACONF_IDEMPOTENCY_TTL: "1800"
  DYNACONF_READINESS_POLICY: "critical"
```

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: checkout-secrets
type: Opaque
stringData:
  DYNACONF_MODEL_API_KEY: "sk-..."
  DYNACONF_CACHE__REDIS_PASSWORD: "..."
```

### Resolution order

Later sources override earlier ones:

1. `settings.toml` -- base configuration, baked into the image
2. each agent's own `settings.toml`, merged under that agent's scope -- filling gaps only, so the
   group's file and any `DYNACONF_<AGENT>__KEY` win over it
3. `secrets.toml` -- local development only; never copied into the image
4. environment variables -- the ConfigMap and Secret above

---

## Sizing a group

Group size is a dial, not an architecture. A group of one gives per-agent process isolation; a
group of twenty shares one runtime, one port, one health endpoint and one broker connection.

What to watch when you turn it up:

- **Memory is the sum of the agents.** Each agent has its own thread pool, its own AI client and
  its own transport subscriptions. Set the pod's memory limit against the group, not against one
  agent, and remember that a memory-limit kill takes the whole group with it.
- **Three failure classes take a whole group down and raise no catchable exception**: the memory
  limit, a native crash, and a blocked event loop. Careful error handling lowers how often a group
  dies; it does not change which failures kill it. That is why attribution is emitted deliberately
  (see *Alerting on an agent*) -- and why the blast radius, not the happy path, is what should
  decide group size.
- **Blocking the event loop is the mistake that only hurts in a group.** In development,
  `app_environment = "development"` puts asyncio in debug mode and names the slow callback itself
  (`event_loop_slow_callback_seconds`, default `0.2`). In production a lower-overhead watchdog
  measures the loop's lag and reports which agents had work in flight when it stalled
  (`event_loop_block_threshold_seconds`, default `1.0`) -- candidates, not a culprit, because by
  the time it runs the blocking call has returned. Debug mode is available in production behind
  `event_loop_debug` at the cost of wrapping every coroutine creation, and the two are never both
  on: with debug mode enabled the watchdog stands down.
- **One agent's failure should not remove the pod.** Use `critical_agents` plus
  `readiness_policy = "critical"` so that a non-critical agent going down is an alert rather than a
  pod out of rotation.

---

## Stateless design

Handlers and services should be designed as stateless components:

- Do not store request-specific state in instance variables. In a group your component is one of
  several in a shared process; across replicas there is no shared memory at all.
- Use the cache service for data that must persist across requests, and Redis rather than the disk
  backend when it must be shared across replicas.
- Use the event bus for inter-service communication rather than in-memory shared state.
- Any initialisation that must happen once belongs in `on_startup()` and must be idempotent: it runs
  once per process, which is once per replica.

---

## See also

- [Multi-Agent Setup](multi-agent-setup.md) -- the model, and migrating an existing agent into a group
- [Caching](../concepts/caching.md) -- backends, named caches, per-agent stores
- [Observability](../concepts/observability.md) -- metrics, traces and what each agent reports
- [Event Processing](../concepts/event-processing.md) -- the ack contract and broker startup
