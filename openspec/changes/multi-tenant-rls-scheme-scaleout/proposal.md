# Multi-Tenant RLS, LangGraph Cutover, and Scheme Scale-Out (to ~25)

## Status

**In progress, 2026-09-15.** Drafted as a stub, then implemented through
group 0 (design defaults applied, not separately signed off — see
`tasks.md` group 0), group 1 (entitlement data model), the buildable core
of groups 2–4 (RLS mechanism + migration SQL + allowlist replacement), and
the LangGraph cutover (group 5) — all flag-gated, defaults unchanged, 39
test files passing. See `tasks.md` for the exact per-task status; the
short version: **not yet safe to enable in production** — curated-data RLS
is blocked on the same DB-role cutover as `phase-1-security-hardening`
item 3, and the LangGraph cutover's real gate (live LLM/DB parity) can't
be run from this environment. Groups 6 (join-graph reload, growth
checkpoint) and 7 (docs) are not started. Per this repo's standing
process, nothing here has been committed — the human commits.

This change ties together three requests that are architecturally
entangled once you follow the actual code, not three independent asks:

1. **Real (DB-enforced) multi-tenancy**, replacing today's app-level-only
   convention.
2. **Postgres Row-Level Security (RLS)**, extended to the curated
   scheme-data warehouse itself, not just the app's own bookkeeping
   tables — confirmed with the user as the intended scope (see
   "Decision: RLS scope" below).
3. **LangGraph production cutover**, continuing/absorbing the existing
   `langgraph-full-pipeline-rewrite` and `phase-2-orchestration-durability`
   work rather than redesigning it.
4. **Scheme onboarding scale-out to ~25 schemes**, addressing the gap the
   archived phase-3 proposal named but explicitly punted
   ("headroom for scheme count to grow well past 4... not a 25-scheme
   rollout").

They're one proposal because (1)+(2) require a tenant↔scheme entitlement
model that (4) also needs as its scaling mechanism, and because (2)'s
implementation touches `app/database/db.py`'s connection-acquisition path — the
same place a LangGraph checkpointer/state cutover (3) naturally lands.

## Decision: RLS scope (confirmed with user, 2026-09-15)

Two options were possible reading the current code:

- **A. RLS only on `app`'s own tenant-owned tables** (users, conversations,
  audit, login_events) — matches today's design intent exactly
  (`app/core/auth.py:120-126` states the curated warehouse is deliberately
  *not* tenant-partitioned).
- **B. RLS extended to the curated/`semantic` scheme-data warehouse**, with
  a real tenant↔scheme grant table replacing the hardcoded per-role scheme
  allowlist, enforced at the DB level.

**User confirmed option B.** This is a real, deliberate reversal of the
"curated data is shared/global, tenant_id never enters the query path"
design recorded in `app/core/auth.py:120-126` and implicitly assumed throughout
`app/orchestration/pipeline.py`/`app/database/db.py`. It is being made explicitly here, the same
way `langgraph-full-pipeline-rewrite/proposal.md:14-22` records its own
reversal of `phase-2-orchestration-durability`'s prior "do not adopt
LangGraph" decision — a deliberate, human-approved scope expansion, not a
correction of a prior mistake.

## Why

### 1–2. Tenancy is real in schema but decorative in enforcement

- `app/database/appdb.py:26-32`, `app/core/config.py:489-493`: tenant = department/
  directorate; `app.tenants`/`users`/`conversations`/`conversation_turns`/
  `query_audit`/`login_events` all carry `tenant_id`.
- Every read of those tables is an app-level `WHERE tenant_id = $N` built
  in Python (`app/database/appdb.py:287-293,361-368`,
  `app/conversation/conversation_store.py:200-251`). Every one of these functions
  accepts `tenant_id: int | None = None` — passing `None` returns **all
  tenants**. There is no server-side default-deny; isolation is 100%
  contingent on every call site remembering to pass the right value.
- `MULTITENANCY_ENABLED` (`app/core/config.py:491`) is a flag nothing branches
  on — dead config.
- `app/core/auth.py:47-60`: `tenant_admin`/`super_admin` are `is_admin: True`
  and bypass all three query-time checks (scheme, geography, granularity)
  — `app/core/auth.py:230-231`. So today, tenant boundaries restrict *nothing*
  about what a query can return; they only partition which conversations/
  audit rows an admin's list view shows. Two `tenant_admin`s from
  different departments get byte-identical DATA-route answers to the same
  question.
- No `ENABLE ROW LEVEL SECURITY`, `CREATE POLICY`, or session-GUC pattern
  exists anywhere in the repo (confirmed by repo-wide search). The
  provisioned least-privilege role (`deploy/sql/01_create_megh_app_role.sql`)
  already sets `NOBYPASSRLS` defensively (line 41) even though no policy
  exists yet — RLS was anticipated, never built.
- `openspec/changes/phase-1-security-hardening/proposal.md:143-147`
  explicitly deferred RLS: *"depends on a stable geography/scheme scope
  model that Phase 3's schema work will formalize; adding RLS now against
  an incomplete scope model risks false security."* No later phase picked
  it up — it is fully unclaimed work, not a partially-done item.
- **Hard shared blocker, not new**: production still connects as the
  `postgres` superuser (`.env`'s `DATABASE_URL`, confirmed multiple
  sessions), not `megh_app`. A superuser bypasses RLS entirely regardless
  of policies defined. This is the *same* infra/ops blocker as
  `phase-1-security-hardening` item 3 (see project memory
  `project-db-role-cutover-blocked`) — this proposal inherits it as a hard
  dependency for production activation, not something it re-solves.
  Development/staging work can and should proceed against a disposable
  non-superuser Postgres (already proven workable this repo:
  `psycopg[binary]`/`AsyncPostgresSaver` verified against a local Docker
  container for `langgraph-full-pipeline-rewrite` tasks 6.3/6.4).

### 3. LangGraph: this is a contract-compliance gap, not just a nice-to-have

**The original Grant Thornton proposal (`GrantThornton_Solution_Proposal_1 (1).pdf`,
repo root — the contracted design this whole project derives from) does
not treat LangGraph as optional.** Direct quote, Section 4:
*"The runtime pipeline is implemented as a LangGraph agent so that
conditional branches, pause-and-resume behaviour for clarifications, and
per-turn state persistence are all handled by the framework rather than by
ad-hoc code."* Also: *"the runtime pipeline (the LangGraph orchestrator and
its worker nodes) implements the per-query logic described in Section 5"*,
and the stack table lists *"Orchestration framework: LangGraph (with Redis
or Postgres checkpointer) — Used in: All; pause/resume."* This means the
prior state — a bespoke, non-LangGraph pipeline as the sole production
path, with LangGraph fully built but never handling a single real request
— was not a deferred enhancement. It was **not yet meeting the contracted
architecture**, the same category of gap `docs/baseline-audit.md` already
documents elsewhere for this project (proposal-vs-actual mismatches).

Prior state, re-verified before this proposal's implementation pass:
- `app/orchestration/pipeline_graph.py` — full 15-node `StateGraph` decomposition of the
  answer pipeline, using LangGraph's real `interrupt()` primitive (the
  exact tool the GT proposal names). `langgraph-full-pipeline-rewrite/tasks.md`:
  every task across all 8 groups checked, including Postgres-checkpointer
  verification against a disposable local Docker Postgres. **But**
  `PIPELINE_GRAPH_ENABLED` (`app/core/config.py`) was defined and read
  *nowhere* (confirmed by a repo-wide grep before this pass) — a fully
  inert flag. Zero references to `pipeline_graph` existed in
  `app/api/routers/query.py` or `app/main.py`.
- `app/orchestration/langgraph_followup.py` — an earlier, narrower module (wraps the
  *whole* existing pipeline as one opaque node, handles only 3
  clarification-pause types, SQLite-only checkpointer). **Was** wired into
  `/api/query`, flag-gated (`LANGGRAPH_FOLLOWUP_ENABLED`, default `False`).
  Partially satisfies the GT quote (pause/resume via `interrupt()`) but not
  the "runtime pipeline IS a LangGraph agent" / "conditional branches ...
  handled by the framework" part — the pipeline's actual branching (scheme
  classification, repair loop, auth, findings, chart selection) still runs
  entirely as ordinary Python inside the one opaque node it wraps.

**Implemented in this pass** (see "What Changes" below): `PIPELINE_GRAPH_ENABLED`
now gates a real branch in `app/orchestration/pipeline.py::_run_pipeline` that routes the
DATA route's §5.1-5.15 chain through `pipeline_graph.py`'s actual
`StateGraph` instead of the bespoke `_answer_data`, closing the gap for
that flag's own request path. Deliberately scoped to only the DATA-route
chain — `_run_pipeline`'s ~3600 lines of edge-case/RAG/scheme-listing
routing that decide whether a question even *reaches* the DATA route are
unchanged, matching `pipeline_graph.py`'s own stated boundary. See "What
Changes" for exactly what was and wasn't verified.
- These two modules currently coexist unreconciled.
  `langgraph-full-pipeline-rewrite/proposal.md:56-59` already says the
  narrow module should be "superseded/absorbed... not left running as a
  third parallel pause mechanism" — that absorption has not happened.
- This proposal is where the deferred go/no-go decision gets made,
  because RLS's `SET LOCAL app.current_tenant_id` hook (see `design.md`)
  needs to land in `app/database/db.py`'s connection path regardless — the natural
  point to also decide the production checkpointer backend and retire the
  narrow module.

### 4. Scheme onboarding: proven at 4, never assessed at 25

- `scheme_registry.yaml`: 4 real schemes + 1 shared entry today.
  `openspec/changes/archive/2026-09-11-phase-3-schema-retrieval-join-discovery/proposal.md:16-23`
  (direct quote): *"there are also only 4 schemes in this codebase today...
  not the 25 an earlier scope reference implied... headroom for scheme
  count to grow well past 4"* — named, then explicitly scoped out:
  *"Pilot... on CM Elevate... prove the onboarding path with Focus Plus as
  the second scheme — not a 25-scheme rollout."*
- Concrete things that do not scale linearly to 25, found by reading the
  actual code (not stated in any prior doc):
  - `app/core/auth.py`'s `ROLE_PERMISSIONS` hardcodes
    `["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate"]` **8 separate
    times** (once per role). Same literal list recurs in
    `app/sql/prompt_builder.py` and `app/response/followups.py`.
  - `app/sql/schema_context.py` is 912 lines of hand-curated per-scheme Python
    (the pre-Phase-3 legacy path, still primary for MGNREGA/PMAY-G) — this
    is the exact "stuffing schema into a prompt" growth pattern Phase 3's
    own proposal warned about; the vector schema-retrieval path is
    additive/supplemental, not a replacement.
  - `app/sql/join_graph.py` only rebuilds at process startup
    (`app/main.py` lifespan) — onboarding scheme N requires a full service
    restart, a real operational cost at 25 vs. 4.
  - Steps 2 and 4 of `docs/scheme-onboarding.md` (SME-authored
    `schema_metadata.yaml` prose, manual FK-candidate review) are
    unautomated human bottlenecks, tractable at 4 schemes, a standing
    backlog problem at 25.

## What Changes

See `design.md` for the concrete schema, session-GUC mechanism, and RLS
policy shape. Summary:

1. New `app.schemes` table (canonical scheme identity, synced from
   `scheme_registry.yaml`) and `app.tenant_schemes` (tenant↔scheme grants,
   many-to-many) — the entitlement model both RLS and scale-out need.
2. RLS enabled on `app.users`, `app.login_events`, `app.conversations`,
   `app.conversation_turns`, `app.query_audit`, `app.tenant_schemes`, keyed
   off a per-transaction session GUC (`app.current_tenant_id`) set in
   `app/database/db.py`'s connection-acquisition path.
3. RLS + `FORCE ROW LEVEL SECURITY` enabled on the 5 real curated FACT
   tables (not the views built over them — Postgres cannot enable RLS on a
   view; see `design.md`'s correction note), policy-checked against
   `app.tenant_schemes` via a `SECURITY DEFINER` helper function. Views
   over those facts (including the two cross-scheme views) inherit
   protection transitively. Shared dimension/lookup tables (`dim_scheme`,
   `dim_year`, `dim_pmay_house_status`, etc.) get no RLS — deliberately,
   not by omission (see `deploy/sql/03_tenant_scheme_rls.sql`'s Category 3
   comment). Blocked for production activation on the existing DB-role
   cutover (superuser → `megh_app`) **and** on confirming the view-owning
   role doesn't have `BYPASSRLS` (a second, separate way RLS can be a
   silent no-op — see `design.md`'s correction note); buildable and
   testable now against a disposable local Postgres.
4. `ROLE_PERMISSIONS`'s hardcoded scheme lists become a role-level cap
   intersected with the tenant's DB-granted schemes, not the source of
   truth. Same for `prompt_builder.py`/`followups.py`.
5. `PIPELINE_GRAPH_ENABLED` cutover — **implemented**: a new
   `pipeline_graph.answer_data_via_graph_compat()` adapter has the exact
   same calling contract as `_answer_data` (raises `ClarificationNeeded`
   for a pause, returns a plain dict otherwise), so
   `app/orchestration/pipeline.py::_run_pipeline`'s single call site swaps to it behind
   the flag with zero changes anywhere else (`app/api/routers/query.py`,
   `app/conversation/session_store.py` untouched). Deliberately does not attempt
   LangGraph's own cross-HTTP-request resume (`resume_via_graph`) — each
   call gets a fresh, throwaway `thread_id`, and a pause is converted
   straight back to `ClarificationNeeded`, letting the existing, tested
   session-merge-and-retry mechanism keep handling cross-turn continuity
   exactly as it does for the bespoke path today. See `design.md` §4a for
   the full reasoning and what a *further* cutover (real cross-request
   graph resume, retiring the session-merge mechanism) would require.
   Still open: production checkpointer choice (SQLite vs.
   `AsyncPostgresSaver`, same DB-role-cutover dependency as item 3), a
   staged/canary rollout mechanism, retirement of
   `app/orchestration/langgraph_followup.py` once parity is confirmed, and — the actual
   remaining gate — end-to-end verification against a live LLM and live
   data across all 4 schemes, which cannot be done from this environment
   (no reachable LLM gateway or production Postgres here).
6. `app.schemes` becomes the source of truth scheme_registry.yaml syncs
   into (via the existing `POST /api/rag/reload-scheme-registry` admin
   endpoint, extended); a `join_graph` reload endpoint removes the
   restart-per-scheme requirement; `schema_context.py`'s growth risk is
   documented with an explicit revisit checkpoint (not migrated here —
   that's `schema-retrieval-reranking`'s scope).

All new behavior is flag-gated (`TENANT_SCHEME_RLS_ENABLED`, default
`False`) so flag-off behavior is byte-identical to today, matching this
repo's existing convention (`LANGGRAPH_FOLLOWUP_ENABLED`,
`PIPELINE_GRAPH_ENABLED`).

## Capabilities

### New Capabilities
- `tenant-scheme-entitlement`: the `app.schemes`/`app.tenant_schemes` data
  model and the API/admin surface for granting a tenant access to a
  scheme.
- `row-level-security`: RLS policies and the session-GUC mechanism, on
  both the app schema and curated/semantic scheme data.
- `langgraph-production-cutover`: the flagged rollout of
  `pipeline_graph.py` into the live `/api/query` path and retirement of
  `langgraph_followup.py`.
- `scheme-onboarding-scaleout`: DB-backed scheme registry, no-restart
  join-graph reload, and the documented `schema_context.py` growth
  checkpoint.

### Modified Capabilities
- `session-ownership`, `sql-repair-authorization`,
  `database-execution-privilege` (from `phase-1-security-hardening`) —
  the DB-role cutover these depend on is shared with this proposal's "Why"
  §1–2 (RLS); no logic change, but their "done" status becomes jointly
  gated on the same infra action.

## Explicitly Out of Scope

- **The production DB-role cutover itself** (superuser → `megh_app`) —
  pre-existing `phase-1-security-hardening` item 3, an infra/ops action
  requiring a maintenance window and production credentials. This
  proposal depends on it for production activation but does not re-scope
  or re-attempt it. Development/staging proceeds against a disposable
  local Postgres.
- **Migrating `app/sql/schema_context.py`'s hand-curated per-scheme blocks**
  to the vector schema-retrieval path — tracked by the existing
  `schema-retrieval-reranking` change. This proposal only documents the
  growth risk and sets a revisit checkpoint.
- **SME authoring-workflow automation** (LLM-assisted
  `schema_metadata.yaml` drafting, FK-review batching) — a real problem
  at 25 schemes per the archived phase-3 proposal, but a content/process
  workstream, not infra. Flagged as a follow-up, not built here.
- **Deciding which of the 25 future schemes belong to which tenant** —
  that's a product/policy decision for the actual rollout. This proposal
  seeds the mechanism with today's reality preserved exactly (the one
  `RD` tenant granted all 4 existing schemes under the flag), so flag-on
  behavior for the current single-tenant deployment is unchanged.
- Legacy ingestion/backfill/quarantine-table code — permanently out of
  scope per standing instruction.

## Impact

- Affected files (expected; confirm exact list during implementation):
  `app/database/appdb.py`, `app/database/db.py`, `app/core/auth.py`, `app/api/deps.py`,
  `app/knowledge/scheme_registry.py`, `app/sql/join_graph.py`, `app/sql/prompt_builder.py`,
  `app/response/followups.py`, `app/orchestration/pipeline_graph.py`, `app/orchestration/langgraph_followup.py`,
  `app/api/routers/query.py`, `app/api/routers/admin.py`, `app/main.py`,
  `deploy/sql/` (new migration files), `scheme_registry.yaml`,
  `docs/scheme-onboarding.md`.
- Schema migration required (new tables + `ENABLE ROW LEVEL SECURITY` +
  `CREATE POLICY` on existing tables) — needs a reviewed migration script
  under `deploy/sql/`, run in staging before any production discussion.
- No public API contract changes expected for `/api/query`'s response
  shape; admin endpoints gain scheme-grant management (new, additive).
- Rollback: **decided** (`tasks.md` 0.2, `design.md` §3) — the RLS
  migration itself (`deploy/sql/03_tenant_scheme_rls.sql`) is a separate
  script, never auto-applied, so flag-off means "the RLS mechanism doesn't
  exist yet in that database," not "exists but silently denies everything
  because the GUC is unset." The app-code side (`app/database/db.py::set_tenant_context`,
  `auth.py::scope_from_user`'s tenant intersection) is already a true no-op
  when `TENANT_SCHEME_RLS_ENABLED=false` — confirmed by the full regression
  sweep passing unchanged at the flag's default. Rollback of the SQL
  migration itself, once applied in an environment, is a separate
  `DROP POLICY`/`DISABLE ROW LEVEL SECURITY` script — not written yet, flag
  as a group 3 follow-up before any environment applies the migration for
  real.
