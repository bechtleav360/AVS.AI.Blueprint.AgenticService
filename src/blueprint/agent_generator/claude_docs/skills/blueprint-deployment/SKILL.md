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

| Shape | Command | Needs group config? |
|---|---|---|
| Standalone | `uvicorn src.main:create_app --factory` | no |
| Standalone, from before the split | `uvicorn src.main:app` | no |
| One agent of a group | `python -m blueprint.agents.entrypoint` | yes: an agent map and a group |

The two images differ in what they copy, not only in how they run. The group image copies the whole
`agents/` tree -- every agent it contains, since which of them a process runs is decided at startup
-- plus `agents.toml` and the process `settings.toml`. A single-agent image copies one agent and no
map at all.

**Both need a `.dockerignore`.** `.gitignore` does not apply to a build context, so a wholesale
`COPY agents ./agents` bakes every agent's `.secrets.toml` into a layer. `asbs setup` writes one.

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
