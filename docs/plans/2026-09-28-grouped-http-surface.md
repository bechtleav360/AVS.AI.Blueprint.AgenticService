# Plan -- A Grouped Agent's HTTP Surface

| | |
|---|---|
| **Amends** | `docs/specs/2026-08-28-multi-agent-grouping.md` -- sec. 11.2 (added in step 0) |
| **Changelog** | `docs/plans/2026-08-28-multi-agent-grouping-changelog.md` |
| **Branch** | `feature/multi-agent-namespaces` |
| **Decided** | 2026-09-28 |

Worked in reviewable steps like the rest of the grouping feature: one step, then a report, then
the next.

---

## Problem

A grouped image's Swagger UI is unusable for the question every reader starts with -- *which
agent do I want to look at?*

- **Most operations sit under "default".** `AppBuilder._mount` rewrites the tags of a namespaced
  component's routes, but only of routes that already carry one (`if isinstance(route, APIRoute)
  and route.tags`). A developer's untagged route keeps `[]`, and FastAPI files it under "default",
  mixed with every other agent's untagged routes.
- **An agent's tagged groups are scattered.** Tags are rendered `<ns>.<tag>` (`orders.nats`,
  `orders.cache`), and Swagger UI lists tags in the order it first meets them, so one agent's
  groups interleave with another's and with "default".
- **Paths have no consistent second level.** Cache routes already carry `cache/`, the scheduler
  trigger carries the scheduler's name, NATS publish carries nothing (`/api/<ns>/events/{topic}`),
  and a developer's routes carry whatever they declare.

## Decisions

1. **One Swagger group per agent.** In a group, every operation of agent `orders` carries exactly
   the tag `orders`, replacing whatever was declared -- the framework's tags and the developer's
   alike. No grouped agent's operation is ever untagged.
2. **The second level is the path, not the tag.** Swagger UI renders tags on one level only, so a
   sub-grouping is expressed as `/api/<ns>/<segment>/...`. Within one agent's group Swagger lists
   operations in registration order, which clusters them by segment without a sorter setting.
3. **Framework segments are reserved.** `nats`, `cache` and `scheduler` belong to the framework
   inside an agent's prefix:
   - NATS publish: `/api/<ns>/nats/events/{topic}`
   - Scheduler trigger: `/api/<ns>/scheduler/<name>/trigger`
   - Cache: `/api/<ns>/cache/*` (unchanged -- its routes already carry `cache/`)
4. **Standalone apps are untouched.** Every rule above applies only to a component with a
   namespace. A standalone agent (root namespace) keeps the tags the framework and the developer
   declare today -- including "default" for untagged routes -- and every path it serves.
   Root components of a grouped app (`root`, `actuators`, `dapr`) are process-wide and keep theirs.
5. **A developer's own prefix is optional.** A developer may declare a path prefix on their API
   class; it applies in both modes, so an agent's code is identical standalone and grouped. It is
   not required: an existing agent joins a group without a code change. What *is* enforced, in a
   group only, is that no developer route starts with a reserved segment.
6. **Rejected: `x-tagGroups`.** A ReDoc vendor extension that Swagger UI ignores; once present,
   ReDoc hides every tag not placed in a group. Revisit only as OpenAPI 3.2 `parent` tags, and
   only once Swagger UI renders them.
7. **Rejected: `<ns> / <tag>` sub-tags.** Superseded by decision 1 -- one group per agent, with
   the path carrying the second level.

The grouped paths change (`/events` -> `/nats/events`, `/<name>/trigger` ->
`/scheduler/<name>/trigger`). Grouping shipped in 0.9.0, so this is a **breaking change for
grouped 0.9 deployments** and is release-noted under *Breaking*. (An earlier draft of this plan
said grouping had not been released; it had.)

## Steps

### Step 0 -- Spec amendment

Add sec. 11.2 *An agent's HTTP surface* to the grouping spec, carrying decisions 1-5 as
requirements, and a row to sec. 10's compatibility table. No code.

### Step 1 -- Framework segments through `route_prefix`

`RestApiBase` gains a class attribute naming a segment that applies only when the component
belongs to an agent, folded into `route_prefix`:

```python
group_segment: str = ""   # "nats" on NatsEventing, "scheduler" on SchedulerBase

@property
def route_prefix(self) -> str:
    if not self.namespace:
        return ""
    return f"/api/{self.namespace}/{self.group_segment}" if self.group_segment else f"/api/{self.namespace}"
```

In `route_prefix` because two places must agree on it: the builder, which mounts the router, and
`DaprEventing.subscribe`, which tells the sidecar where to post (`dapr.py:199`). `DaprEventing` is
always root and so unaffected, but it must stay reading the same property.

Tests: grouped NATS and scheduler paths; standalone paths unchanged; the frozen compatibility suite
unchanged.

### Step 2 -- One tag per agent

`AppBuilder._mount`: for a namespaced component, every `APIRoute`'s tags become
`[component.namespace]`, whether or not it had tags. Root components are left alone.

Tests: an untagged grouped route is tagged with its agent; a tagged one loses its own tag; two
agents never share a tag; root and standalone tags unchanged. The expectations in
`test_route_namespacing.py` (`orders.orders`, `billing.orders`) change accordingly.

### Step 3 -- Developer prefix and reserved segments

- An optional class attribute on `RestApiBase` for a developer's own path prefix, applied in both
  modes. The attribute's name and its interaction with `group_segment` are settled in this step.
- `build()` fails with a message naming the component, the route and the segment when a grouped
  agent's developer route starts with `nats`, `cache` or `scheduler`. Framework components are
  exempt, since they are the owners.

### Step 4 -- Documentation

`guides/multi-agent-migration.md` and the `blueprint-migration` skill (tags and paths in a group;
the reserved segments; the optional prefix), the `with_rest_api` / `with_scheduler` docstrings
that describe the grouped paths and tags, `CHANGELOG.md`, and the feature changelog.

## Out of scope

Routes added directly to the `FastAPI` application in `main.py` (`@app.get`,
`app.include_router`) never pass through `_mount` and can still land in "default". A check after
`build()` could catch them; not planned unless asked for.
