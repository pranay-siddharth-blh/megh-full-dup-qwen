# Phase 6 — Observability & Deployment Alignment

## Status
**Approved for implementation, scoped to per-user rate limiting** —
both open questions resolved 2026-09-15 (see that update below): the
Kubernetes item is ratified/documented, not acted on; per-user rate
limiting is the one real code change, covered by
`specs/rate-limiting/spec.md`/`design.md`/`tasks.md`. Originally derived
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

**Update (2026-09-12):** both the storage/retention divergence and the
audit-log-field-expansion coupling above are now resolved. Storage
(JSONL + Postgres mirror) and the 365-day retention window
(`deploy/sql/02_retention_policy.sql`) are ratified as the permanent,
intentional design for this deployment's two-VM scale — no ClickHouse
adoption, no retention-window change. Field expansion (executed SQL,
result preview, findings, chart_type) is carved out into its own
change, `phase-2-audit-trail-enrichment`, decoupling it from this
stub's remaining scope. The Kubernetes/deployment-topology question and
the per-user-rate-limiting question are unchanged and still open.

**Update (2026-09-15) — both remaining open questions resolved by explicit
product decision, this stub is now approved for implementation on that
scope:**

1. **Kubernetes migration: ratified as not warranted, documented rather
   than acted on.** Consistent with every other heavier-infra divergence
   this repo has already ruled on the same way (ClickHouse/Langfuse/
   Prometheus, LangGraph full-pipeline orchestration) — the operative
   reasoning each time is the same: a 2-VM, ~20-40-concurrent-user
   deployment is exactly the scale at which the heavier option's
   operational cost isn't repaid. No Kubernetes manifests are being
   written; `deploy/DEPLOYMENT.md`/systemd remain the permanent target.
   This closes the "Not yet decided" item above with no code change.
2. **Rate limiting: move from per-IP-only to per-user.**
   `app/middleware/rate_limit.py` keys its sliding window by client IP
   today; every `/api/query` caller already carries a validated JWT
   identity (`app/deps.current_scope`) by the time a request reaches the
   route, this middleware just runs earlier in the stack (before route
   dependency injection) so it needs to decode the bearer token itself —
   cheaply, via the same `app.security.decode_token` HMAC/signature/
   expiry check already used elsewhere, no extra DB round-trip. See
   `design.md` for the exact mechanism and `specs/rate-limiting/spec.md`
   for the behavior contract.

Scope of this change, per those two decisions: **rate limiting is the
only code change**; the Kubernetes item is documentation-only (this
proposal + `docs/baseline-audit.md`'s own update convention).

## Capabilities

### New Capabilities
- `rate-limiting`: per-caller request throttling on `/api/query` and
  `/api/auth/login`, keyed by authenticated user identity when a valid
  bearer token is present, falling back to client IP otherwise (`openspec/
  specs/` has no existing rate-limiting capability yet).

### Modified Capabilities
(none)
