---
name: blueprint-deployment
description: Deploying a Blueprint Agents service - Docker images, Kubernetes and Helm, health probes, replicas, schedulers under scale, and the writable cache directory. Use when building an image, writing manifests, scaling replicas, or diagnosing a probe or CronJob failure.
user-invocable: true
---

# Deployment

```bash
asbs docs guides/deployment --cat     # images, Helm, probes, replicas, schedulers, sizing
```

Sections, in order: The image, Choosing what a process runs, Kubernetes with Helm, Running more than
one replica, Schedulers, Health probes, Writable cache directory, Configuration, Sizing a group,
Stateless design.

## What a process runs is a deployment decision

The image is the same whether it hosts one agent or ten. What differs is the command and the agent
map - see `blueprint-multi-agent`. Changing the mix is an edit to a Deployment, not a rebuild.

| Shape | Command |
|---|---|
| Standalone | `uvicorn src.main:app` (or `src.main:create_app --factory` once migrated) |
| Grouped, including a group of one | `python -m blueprint.agents.entrypoint` |

## The two that break under replicas

- **Schedulers.** `scheduler_mode = "in_process"` runs a timer in *every* replica and relies on the
  cache to claim each tick, so without `.with_cache()` every replica runs every tick.
  `scheduler_mode = "event"` starts no timer at all - an external `CronJob` publishes the tick and
  the queue group already guarantees one consumer. Read *Schedulers* and *Running more than one
  replica* together before scaling past one.
- **The cache directory must be writable.** The disk backend needs a writable volume; a read-only
  root filesystem fails at startup, not at first use. See *Writable cache directory*.

## Probes

Health endpoints are covered under *Health probes*, and only one readiness probe is answered per
process - in a group, a copy of the probe config scoped under a single agent is read by nothing.
`asbs validate` reports that case.

## Before shipping

- Secrets come from the environment or a mounted `.secrets.toml` - never baked into the image.
- Keep components stateless; *Stateless design* explains what that rules out.
- Size a group deliberately: *Sizing a group* runs the dial from full process isolation to twenty
  agents sharing one runtime.
