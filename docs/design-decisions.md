# Design Decisions

> Last updated: 2026-03-24

## Table of Contents

- [Architecture Decision: SA-AI Recommendation Process](#architecture-decision-sa-ai-recommendation-process)

---

## Architecture Decision: SA-AI Recommendation Process

**Status**: Proposed
**Date**: 2026-03-24
**Components**: SA-AI, Backend, Recommendation Store

### Context

When SA-AI reacts to events created from the backend, one type of task is to evaluate an object or a field of an object in the database. In those cases the SA-AI may want to update, create, or delete objects. However, SA-AI is not allowed to make any changes that are not approved by a user. Therefore, a recommendation process is required.

### Decision

SA-AI gets its own database space (accessible exclusively via a GraphQL API) where it can store recommendations.

#### Recommendation Store

- Contains both **structured fields** and a **dynamic JSON field**.
- The dynamic field is used by the SA-AI for internal management of the recommendation. Each SA-AI may define its own structure but is obligated to keep it simple.
- The structured fields contain both metadata (version, created date, changed date, TTL) and the recommendation payload itself.
- A recommendation payload stores the **intent** of the change as structured data (entity type, operation, target ID, fields to change) — not an executable GraphQL query. The backend generates and executes the actual query at approval time. This decouples the recommendation store from the current GraphQL schema, preventing stale queries caused by schema evolution.

#### Field Ownership

Each field of a domain object is owned by exactly one SA-AI. An SA-AI is the sole agent responsible for recommending changes to its assigned fields. This constraint must be enforced technically (e.g., via a unique index or registry mapping `(entity_type, field_name) → agent_id`) rather than by convention alone.

#### Recommendation Lifecycle

A recommendation follows a strict state machine:

```
PENDING → EXECUTED   (backend executed the recommendation after user approval)
        → REJECTED   (user explicitly rejected the recommendation)
        → EXPIRED    (TTL elapsed before the user acted)
        → RETRACTED  (SA-AI self-cancelled the recommendation before review)
```

- `EXECUTED`, `REJECTED`, `EXPIRED`, and `RETRACTED` are terminal states.
- A recommendation is **immutable** once created. An SA-AI may only transition its own pending recommendation to `RETRACTED` — no other modifications are allowed.
- A follow-up recommendation for the same field may only be created after the previous one has reached a terminal state.
- `EXPIRED` and `REJECTED` are distinct terminal states to preserve auditability: expired means no user action was taken, rejected means the user made a deliberate decision.

#### Notifications

When a recommendation is created, the SA-AI emits a notification event to inform the backend. Notifications are communicated via the event bus. The recommendation creation and notification emission must be treated as a single atomic operation (e.g., via the outbox pattern) to prevent silent failures where a recommendation exists but was never surfaced to users.

### Alternatives Considered

**Store recommendations as executable GraphQL queries**
Rejected. Schema changes can silently invalidate stored queries (renamed fields, type changes). Storing executable queries also increases the attack surface and is harder to validate or sanitize. Storing structured intent and generating the query at execution time is more robust.

### Trade-offs

- Storing intent rather than executable queries requires the backend to maintain a query-generation layer at the point of approval. This adds a small amount of backend complexity in exchange for long-term resilience to schema changes.
- TTL-based expiry adds a cleanup mechanism but requires a background process to transition recommendations to `EXPIRED` on schedule.
- The one-agent-per-field constraint limits flexibility but is necessary to prevent conflicting recommendations and ambiguous ownership.

### Consequences

- SA-AI has no direct write access to the main application database — all changes go through the human-approved recommendation flow.
- The recommendation store serves as an audit log of all AI-suggested changes and their outcomes.
- The `RETRACTED` state gives SA-AI a correction mechanism when it detects its pending recommendation is no longer valid, without compromising immutability.
- Append-only recommendations with follow-ups only after resolution keep the state per field unambiguous at all times.

### Review Notes

- **Rationale Reviewed**: Yes
- **Alternatives Documented**: Yes
- **Components Identified**: Yes

---
