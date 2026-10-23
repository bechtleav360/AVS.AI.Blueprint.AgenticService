# Proposal -- One startup pass that says everything the configuration is missing

| | |
|---|---|
| **Status** | Proposal. Raised in discussion 2026-09-10; not implemented, not scheduled. |
| **Relation to the grouping work** | **None. Do not touch this during the builder rewrite.** Explicitly carved out of `2026-09-10-builder-unification.md`. |
| **Intended to be** | Non-breaking: the set of keys that must exist does not change. |

## Why this is separate

The builder rewrite changes *where* configuration is handed in (`build(config)` instead of
`__init__`) and *how* an agent's fragment is merged. It does not change what happens when a key is
missing -- and it should not, because the two would then fail together and neither could be
reviewed on its own. This document is the second half, kept apart on purpose.

## What exists today

There are **four** unrelated mechanisms deciding what happens when a setting is absent, and they
disagree about whether that is an error, a default, or nothing at all.

### 1. Three Dynaconf validators that cannot fail

`config.py:161-168` declares `app_name`, `app_port` and `app_environment` with
`must_exist=True` -- and with `default=`. Verified against the installed Dynaconf:

```
Validator("app_name", must_exist=True, default="agent_blueprint")  ->  'agent_blueprint'
Validator("app_name", must_exist=True)                             ->  ValidationError
```

When a default is present it is injected and `must_exist` never fires. So of the three
declarations, the only condition that can actually fail is `is_type_of=int` on `app_port`. An
application with no `settings.toml` at all starts, and calls itself `agent_blueprint`.

That is a defensible policy -- these three have sensible defaults. It is not defensible that the
code says `must_exist=True`, because the next person to add a genuinely required key will copy the
pattern and get a silent default.

### 2. `Config.validate()`, whose two real checks run somewhere unreachable

`validate()` (`config.py:836`) is called from `Config.__init__` (`config.py:187`) and **raises**
`ConfigError`. Beyond the validators it checks two things by hand: `app_port` in range, and an
API key when the provider is `vllm`.

Because it raises during construction, a `Config` object that exists has always passed. Therefore
`_validation_errors` is always empty on any live instance, and the two places that read it --
`actuator_api.py:95` in readiness and `actuator_api.py:149` in liveness -- are **dead branches**.
The readiness probe was written to report configuration failure as a 503 with the reasons in the
payload; it cannot, because the process never reaches the point of serving. Worth deciding
deliberately which of the two behaviours is wanted rather than leaving both in the tree.

### 3. Typed getters that turn a missing key into a default, silently

`get_ai_config`, `get_cache_config`, `get_observability_config`, `get_event_publishing_config`,
`get_prompt_config`, `get_runtime_config`, `get_nats_subscription_config` each read keys with
`self.get(key, <default>)` and hand back a Pydantic model. A typo'd or absent key is
indistinguishable from one deliberately left out: the model is fully populated either way.

This is where a missing *required* setting hides longest, because the value only turns out to be
wrong much later, in a component, as a connection failure or an empty result.

### 4. Per-component checks, each at a different moment

| Check | Where | When it fires |
|---|---|---|
| `model_name`, `provider`, provider supported | `agent_builder.py:108-114` | declaration time, in `main.py` |
| `sessions_service` present, `base_url`, `agent_id`, `api_key` | `sessions_bus.py:88-107`, `api_client.py:50-58`, `key_provider.py:71-185` | first connect |
| `idempotency_ttl` numeric | `handler_chain.py:563` | first event |
| `scheduler_mode` in range | `scheduler.py:352` | startup |
| any numeric NATS key | `nats_client.py:444-451` | on read |

Each message is good in isolation -- most name the key and the accepted values. The problem is the
aggregate: a deployment missing three keys is fixed in three deploy cycles, because each failure
hides the next, and some of them wait for the first request.

## What to build

### One declaration point

A component declares what it needs, next to the code that reads it:

```python
class SessionsBus(ApiBase):
    required_config = (
        Required("sessions_service.base_url"),
        Required("sessions_service.agent_id"),
        Required("sessions_service.api_key", secret=True),
        Required("sessions_service.max_concurrent_jobs", default=10, is_type=int),
    )
```

`secret=True` keeps the value out of the message: a validation error may say the key is missing,
never what it holds.

### One pass, reporting everything at once

At the end of `build()`, after every component is registered and each one's namespace is known,
one pass walks the declarations, resolves each key **through that component's own configuration
view**, and collects failures. If there are any, it raises once:

```
Configuration is incomplete. 3 required settings are missing or invalid:

  billing.sessions_service.agent_id   missing      required by SessionsBus (agent 'billing')
  orders.idempotency_ttl              not an int   required by HandlerChain (agent 'orders'), got 'thirty'
  cache.redis_host                    missing      required by RedisCacheService (agent 'orders')
```

Three properties this needs to have:

- **Every failure, not the first.** That is the whole point.
- **The agent named.** In a group, "missing `sessions_service.agent_id`" does not say whose, and
  D5 of the builder proposal makes each agent's fragment its own -- so the answer is per agent.
- **Before the port is bound.** Same rule as the group resolution failure in `entrypoint.main`:
  a pod that binds its port has told Kubernetes it is a healthy replica.

### Keep the required set exactly as it is

The migration risk here is entirely in scope creep. Declaring a key required that today has a
silent default breaks a running deployment at its next restart, and it will not be obvious that a
configuration-validation change did it. So the first implementation transcribes what the four
mechanisms require **today** and nothing more:

- The three root validators keep their defaults, declared as defaults rather than as
  `must_exist=True`.
- Every check in mechanism 4 keeps the same condition, moved to a declaration.
- The typed getters' defaults stay defaults.

Anything that *should* become required is a second, separate change with its own migration note.

### Decide what the actuator reports

Once the pass exists, the dead branches resolve one way or the other:

- **Fail the process** (today's actual behaviour): drop `has_validation_errors`,
  `get_validation_errors` and both actuator branches. Simplest, and matches
  "a misconfigured pod must not serve".
- **Fail readiness** (what the actuator was written for): keep the errors as data, serve
  `/health/live` as UP and `/health/ready` as 503 with the reasons, and let an operator read them
  from the probe rather than from pod logs.

The second is more useful in a cluster and is what the code intends; the first is what the code
does. Not decided here.

## What this does not cover

- `models/config.py`'s topic-mapping parser, which validates *shape* rather than presence and is
  already loud and well-tested.
- Making anything newly required (above).
- `asbs validate`, which could run the same pass at authoring time once it exists -- worth doing,
  but after.

## Sequence, when it is picked up

1. `Required` value object and the `required_config` class attribute; no behaviour change.
2. The startup pass, reporting collected failures, wired into `build()`.
3. Transcribe mechanisms 1, 2 and 4 into declarations; delete the hand-written checks as each is
   covered by a declaration and a test.
4. Decide the actuator question and remove whichever half loses.
