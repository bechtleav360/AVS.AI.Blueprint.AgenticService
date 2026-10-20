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
  in both scheduler modes (in `in_process` mode only on a shared Redis cache), and event
  deduplication is available. What you have to decide is listed
  under [Running more than one replica](#running-more-than-one-replica).

> **The delivery behaviour is tested against a real NATS server** (`tests/integration`, a
> `nats:2.10` broker with JetStream): acknowledgement exactly once, redelivery after `nats_ack_wait`,
> concurrent runs, the `in_progress` heartbeat, the run timeout, reconnect with resubscription and
> named connections on an account-per-connection broker. Distribution across several *pods* has
> been measured with several clients in one test process, not with real pods; treat the first
> multi-replica deployment accordingly.

---

## The image

**There are two, and which one you have depends on what you scaffolded.** `asbs setup <name>`
writes a single-agent image that serves one declaration directly -- `uvicorn src.main:create_app
--factory`, no map, no group, no namespace. `asbs setup --group` writes a group image, which is
the one below. The same agent directory is built by either without editing a line; what differs
is what gets copied and what serves it.

The group image's runtime stage, as `asbs setup --group` writes it (comments shortened):

```dockerfile
FROM python:3.13-slim-bookworm AS runtime

RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# The agents, each in the directory its entry in agents.toml points at with `root`.
COPY --chown=appuser:appuser agents ./agents
COPY --chown=appuser:appuser settings.toml ./
COPY --chown=appuser:appuser agents.toml ./

# The disk cache backend writes here and cannot create it itself: WORKDIR made /app root-owned.
RUN mkdir -p /app/.cache && chown -R appuser:appuser /app/.cache

ENV DYNACONF_APP_ENVIRONMENT="production" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health/live', timeout=4).status == 200 else 1)"]

ENTRYPOINT ["python", "-m", "blueprint.agents.entrypoint"]
```

Five things about it are load-bearing:

- **`agents.toml` is copied in; the group file is not.** The map says what the image *contains*, and
  changes only when an agent is added or removed -- which is a rebuild anyway. Which agents a
  *process* runs is a deployment decision and arrives separately, so baking it would defeat the one
  property the whole model exists for.
- **The command is `python -m blueprint.agents.entrypoint`**, which is what makes this a *group*
  image. A scaffolded `src/main.py` declares an agent and also offers `create_app()`, so the same
  file is served directly by a single-agent image and hosted by this one; the entry point resolves
  this process's group, builds it and serves it. A project from before the split, whose `main.py`
  builds its own application, keeps `uvicorn src.main:app` and keeps working.
- **`.secrets.toml` is never copied in.** Mount it, or supply the values as environment variables.
  The `agents/` tree is copied whole, so it is the `.dockerignore` that `asbs setup --group` writes
  that keeps each agent's own `.secrets.toml` out of the image.
- **`app_environment` defaults to `development`, and a deployment sets `production` itself.** The
  variable is `DYNACONF_APP_ENVIRONMENT` (`<PREFIX>_APP_ENVIRONMENT` with a custom `envvar_prefix`);
  `DYNACONF_ENVIRONMENT` selects nothing. Left at `development`, a process logs a WARNING at startup
  that it runs in development mode, falls back to a localhost broker (with a WARNING) when
  `nats_url` is unset, and serves one uvicorn worker at log level `debug`. Asyncio debug mode is
  not part of it: that is `event_loop_debug`, off unless set.
- **The health check is Python, not `curl`:** the slim base image has no `curl`, so a `curl` check
  fails for ever and the container never turns healthy.

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
for the NATS connection name (`<agent>.<group>.<pod>`; a standalone agent's is the pod alone), which
is what makes "which replica did that" answerable from the broker's own connection list.

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
without the others. Every name in `critical_agents` must be an agent the group runs -- also when
`BLUEPRINT_AGENTS` replaces the file's agent list -- or startup fails: a name that matches none
would make every agent non-critical. `agents` and `critical_agents` are lists (`[order]`, never a
bare `order`), a group name appears once per file, and a group none of whose agents could be loaded
fails startup instead of running empty.

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
| Handled, skipped (`HandlerResult.skipped`), or no handler matched it | **ack** -- none of them is a failure |
| A retryable failure | **nak**, redelivered at once (no delay is set) |
| A run that exceeded `nats_handler_timeout` | cancelled and **nak**'d for immediate redelivery |
| A poison payload, or a `CriticalHandlerError` | **term**, and dead-lettered |
| `nats_max_deliver` attempts exhausted | dead-lettered |

Keys to set deliberately. Unset, each is the server's default: the framework sets no consumer
setting on its own.

- **`nats_ack_wait`** (server default: 30 s on NATS). A running JetStream delivery reports
  `in_progress` every third of it (`nats_heartbeat_enabled`, on by default), so a long run is not
  redelivered while it runs. What the heartbeat does not cover is a message that is still waiting in
  the client's queue -- bound that with `nats_max_ack_pending`. With the heartbeat switched off,
  `nats_ack_wait` must exceed your p99 handler duration (and dedup warns at startup; see below).
- **`nats_handler_timeout`** bounds a single run; set it above the longest legitimate run.
- **`nats_max_ack_pending`** is the in-flight limit **across every replica sharing the consumer**,
  not per replica. Set it deliberately: it decides how many messages all replicas together work on
  at once.
- **`nats_max_deliver`** bounds retries. Unset it is unlimited, so a message that keeps failing is
  retried forever and never dead-lettered.
- **`nats_max_concurrent_runs`** (unset: one per subscription) is how many deliveries one pod runs at
  once per agent.
  An agent that waits on models most of the time can run many at once on one event loop; set
  `nats_max_ack_pending` to about replicas x this value, so pods do not hoard messages they cannot
  start yet.

### 3. Deduplication, if your handlers need it

Delivery is at-least-once, permanently: a lost acknowledgement, a pod killed mid-handler or a
rolling deploy each produce a redelivery *after* the first attempt has committed its side effects.
Two honest answers, and the framework will not choose for you:

- make the services the handlers call safe to repeat (upsert rather than insert, key the outbound call on
  `event.id`), or
- set `idempotency_enabled = true` and `idempotency_ttl`.

**The TTL must outlast the broker's redelivery window**, which is
`nats_ack_wait * nats_max_deliver` -- so dedup needs `nats_max_deliver` set, since unlimited
retries have no window to outlast:

```
300 s x 5 = 1500 s     # nats_ack_wait = 300, nats_max_deliver = 5
idempotency_ttl = 1800 # with headroom for clock skew and a slow restart
```

Too short and a redelivery arrives after the marker has expired, which is the case dedup exists to
prevent. Too long only costs cache entries. If you raise `nats_ack_wait` or `nats_max_deliver`,
raise this with them.

Two limits to know: dedup needs the agent to declare `with_cache()` -- the marker lives in that
agent's own cache, and without one startup fails -- and the claim is atomic only across replicas
that share a Redis cache. A disk cache's claim holds within one process: replicas sharing a cache
directory (or `uvicorn --workers N` run by hand) can both win it, so they can both run one event or
one tick.

A marker has no "in progress" state, so dedup relies on the broker not redelivering a run that is
still going. Where nothing guarantees that -- NATS with `nats_heartbeat_enabled = false`, or Dapr,
which has no heartbeat -- the agent logs a WARNING at startup: keep runs well under `nats_ack_wait`
or the sidecar's app-call timeout.

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
adapter. Check `nats_max_ack_pending` and `nats_max_concurrent_runs` before adding replicas: the
first limits the in-flight messages of all pods together, so more pods under the same limit do not
process more at once; the second is often the cheaper lever, since a pod waiting on models has
event-loop time to spare.

---

## Schedulers

`scheduler_mode` has no default and is required as soon as a scheduler is registered, because
neither value is safe to inherit. It resolves **per agent**, so one agent may run an in-process
timer beside a neighbour driven by external ticks.

### `scheduler_mode = "in_process"`

An APScheduler timer runs in every replica, and each tick is **claimed** in the agent's own cache --
a marker keyed on the scheduler and the minute the tick was scheduled for (not the clock when it
ran) -- so the replica that stores it runs the tick and the rest do not. Nothing is elected and
nothing is held, so there is no lease to renew and none to be left behind by a replica that dies.

It needs `.with_cache()` on that agent, and a Redis cache shared by the replicas. Without a cache the
claim has nowhere to go and **every replica runs every tick**; the framework logs this at startup and
`asbs validate` reports it. A disk cache's claim holds within one process only, so with a per-pod
disk cache every replica runs every tick too. Right for local development, plain Docker, and a
single-replica deployment.

### `scheduler_mode = "event"`

No timer runs in the process at all. The tick arrives as an ordinary event on

```
<agent>.scheduler.<scheduler name>
```

-- the agent's namespace, or `app_name` for a scheduler at the root, then the scheduler's own name
without the agent (`order.scheduler.nightly`). It is the queue group that
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
`/status/llm`, `/status/build`. There is no `/health/detailed`. `/status/env` masks every key that
names a secret (`key`, `token`, `password`, `secret`, ... and `pass`, `dsn`, `conn` as words) together
with any section under it, a URL's userinfo, secret query parameters (`token=`, `sig=`) and
`Name=value` segments of connection strings (`AccountKey=`); a URL whose userinfo cannot be told
from the rest is masked whole. Treat it as an operator endpoint all the same.

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
longer derivable from `components`: the pod above answers `UP` with a failing check in it. Both
`policy` and `namespaces` appear only when the process hosts a group; a standalone agent's payload
is `status` and `components`.

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
`scheduler_mode`, `readiness_policy`. The sectioned ones are `cache.*`, `event_publishing.*` and
`runtimes.<name>.*` (with its legacy singular `runtime.<name>.*`).

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
2. `.secrets.toml` beside it -- mounted at runtime, never copied into the image
3. environment variables -- the ConfigMap and Secret above

Each agent's own files are merged under that agent's scope after these, filling gaps only -- so
everything above, `DYNACONF_<AGENT>__KEY` included, wins over them. Its `.secrets.toml` is merged
first and so wins over its `settings.toml`; no value from it is logged.

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
- **Blocking the event loop is the mistake that only hurts in a group.** A low-overhead watchdog
  measures the loop's lag and reports which agents had work in flight when it stalled
  (`event_loop_block_threshold_seconds`, default `1.0`) -- candidates, not a culprit, because by
  the time it runs the blocking call has returned. `event_loop_debug = true` puts asyncio in debug
  mode instead, which names the slow callback itself (`event_loop_slow_callback_seconds`, default
  `0.2`) at the cost of wrapping every coroutine creation; it is off unless set, in development
  too. The two are never both on: with debug mode enabled the watchdog stands down.
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
