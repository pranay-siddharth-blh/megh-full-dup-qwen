# Phase 6 — Observability & Deployment Alignment (stub)

## Status
Stub — scope statement only, not yet approved for implementation. Derived
from `docs/baseline-audit.md` §2 (11.3), §3 (findings 4, 6).

## Scope (one paragraph)

Reconcile the proposal's deployment and observability narrative against
what Phase 0 confirmed is actually running. Production is systemd + nginx
on two bare VMs (`deploy/DEPLOYMENT.md`, `deploy/systemd/`), not
Kubernetes; there are no Kubernetes manifests anywhere in the repo, and
`docker-compose.yml`'s single `local-infra` profile is a local-dev
convenience, not the proposal's dev/staging split. The audit trail is
~15 fields of JSONL + a Postgres mirror with a 365-day purge policy
(`deploy/sql/02_retention_policy.sql`), not a full per-query trace stored
indefinitely in ClickHouse — ClickHouse, Langfuse, Prometheus, Grafana, and
Loki are all confirmed absent from the repo. Decide, item by item, whether
each divergence is an intentional and acceptable simplification for this
deployment's actual scale (two VMs, not a Kubernetes-scale rollout) or a
real gap worth closing — and if closing, what the minimum viable version
looks like (e.g. richer JSONL/Postgres fields rather than a full ClickHouse
adoption). Also decide whether rate limiting should move from the current
per-IP-only scheme (`app/middleware/rate_limit.py:34-42,66-67`) to
per-user, now that every route already carries a validated JWT identity.

## Not yet decided

- Whether Kubernetes migration is ever warranted given the current
  two-VM scale, or whether this divergence should simply be documented as
  the proposal being aspirational/scale-driven rather than acted on.
- Audit-log field expansion is coupled to the Phase 2 durability decision
  (both touch `auth.audit()`/`conversation_store.py`) — sequencing between
  the two phases needs to be decided before either starts.

This stub requires its own approval and design review before work starts.
