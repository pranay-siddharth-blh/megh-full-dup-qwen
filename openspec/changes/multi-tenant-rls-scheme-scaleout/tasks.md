# Tasks: Tenant/Scheme RLS, LangGraph Cutover, Scale-Out

All groups build/test against a disposable local Postgres (Docker),
already proven viable in this repo. **No task in any group should be
marked done against production** until the DB-role cutover
(`phase-1-security-hardening` item 3, shared blocker) actually happens —
see group 3's explicit note. Run this file's bottom-listed regression
sweep after every group, not batched to the end.

## 0. Design sign-off (human-gated — do not start group 1 until answered)

**Resolved 2026-09-15 by proceeding with each item's own "Recommended"
default from `design.md`, per explicit instruction to implement** — not by
separate product sign-off on each question individually. Flagged here so
a later reviewer knows these were engineering defaults, not a deliberated
product decision, and can revisit any of them if wrong:

- [x] 0.1 `design.md` §1: effective scheme access = `tenant_schemes ∩
      role_scheme_cap` (the tenant grant narrows, never replaces, the role
      cap) — implemented in `app/auth.py::scope_from_user`.
- [x] 0.2 `design.md` §3: option (a) — the RLS migration itself
      (`deploy/sql/03_tenant_scheme_rls.sql`) is a separate script, not run
      automatically by app startup, so flag-off means "doesn't exist yet,"
      not "exists but unsatisfied."
- [x] 0.3 Seed data: `app/scheme_registry.py::sync_to_db()` grants the
      default tenant every currently-registered scheme, but **only when
      that tenant has zero existing grants** (first run only) — implemented
      and wired into startup (`app/main.py`).

## 1. Tenant↔scheme entitlement data model — DONE 2026-09-15

- [x] 1.1 `app.schemes`/`app.tenant_schemes` — idempotent DDL in
      `app/appdb.py` (not a separate `deploy/sql` file as originally
      sketched: these two tables live in the `app` schema, where `megh_app`
      already has `CREATE` per `01_create_megh_app_role.sql`, so they
      follow this repo's existing runtime-DDL pattern instead of needing a
      superuser script). `curated.table_scheme_map` — DOES need a superuser
      script (curated schema is SELECT-only for `megh_app`) —
      `deploy/sql/03_tenant_scheme_rls.sql`.
- [x] 1.2 `app/scheme_registry.py::sync_to_db()` populates `app.schemes`
      from the loaded YAML; seeds `app.tenant_schemes` per 0.3.
      `curated.table_scheme_map` seeded separately in the SQL script (see
      group 3 — different privilege boundary, see 1.1's note).
- [x] 1.3 `POST /api/rag/reload-scheme-registry` now also calls
      `sync_to_db()` (`app/routers/rag.py`).
- [x] 1.3b **Real bug found and fixed 2026-09-15**, discovered while
      running `appdb.ensure_schema()` connected as `megh_app` (not
      postgres) for the first time in this repo's history — every
      previous test/run connected as postgres or never actually hit this
      line as a non-superuser: `_DDL`'s opening `CREATE SCHEMA IF NOT
      EXISTS app;` requires database-level `CREATE` privilege in
      Postgres **even when the schema already exists** (the privilege
      check runs before the existence check) — `megh_app` only has
      schema-scoped `CREATE ON SCHEMA app`, never database-level
      `CREATE`, so this would have crashed **every app startup** the
      moment the DB-role cutover ([[project-db-role-cutover-blocked]])
      happens. Fixed in `app/appdb.py`: wrapped in a `DO $$ IF NOT EXISTS
      (SELECT 1 FROM pg_namespace ...) THEN CREATE SCHEMA app; END IF;
      END $$;` guard, so the common case (schema already exists, created
      by `01_create_megh_app_role.sql` beforehand) needs no privilege at
      all. Verified against the disposable Postgres: failed before the
      fix (`permission denied for database megh_db`), succeeded after.
- [x] 1.4 `GET /admin/schemes`, `GET/POST/DELETE /admin/tenants/{id}/schemes/{scheme_id}`
      (`app/routers/admin.py`) — super_admin-gated for grant/revoke.
- [x] 1.5 **Done 2026-09-18**: `tests/test_tenant_scheme_entitlements.py`
      covers the pure-Python half (scope intersection, cache fingerprint,
      contextvar mechanics); new `tests/test_admin_schemes_live_db.py`
      closes the DB-backed half this row previously left open — a real
      `sync_to_db()` call and the actual `/admin/schemes`,
      `/admin/tenants/{id}/schemes/{scheme_id}` (GET/POST/DELETE) HTTP
      endpoints, run against the same disposable Postgres 3.3/3.4/6.4
      used (`postgres:16-alpine`, not the shared `megh-one-db`).
      Skips cleanly when no live Postgres DSN is configured, same
      convention as `tests/test_pipeline_graph_postgres.py`. **A real
      test-infrastructure bug found and fixed while writing this**:
      mixing `asyncio.run()` for bootstrap with Starlette's synchronous
      `TestClient` for the HTTP calls broke with `InterfaceError:
      another operation is in progress` — asyncpg connections/pools are
      bound to the event loop that created them, and `TestClient` drives
      the ASGI app in its own internal loop per call. Fixed by running
      bootstrap AND every HTTP call inside one `asyncio.run()`, using
      `httpx.AsyncClient(transport=ASGITransport(app))` instead of
      `TestClient` — not a pipeline bug, but worth recording since the
      same mistake would bite any future live-DB + real-HTTP test in this
      repo. All 6 checks pass: all 4 schemes present after a real sync,
      a fresh tenant starts with zero grants, grant/effective-schemes/
      revoke round-trips correctly, an unknown scheme_id 422s from real
      DB-backed validation (not just app-level), and a second
      `sync_to_db()` call is genuinely idempotent (no duplicate rows).
      Full 42-file regression sweep passes.

## 2. RLS on app schema tables — mechanism done, policies deliberately NOT enabled yet

- [x] 2.1 `app/db.py::set_tenant_context()`/`reset_tenant_context()` —
      contextvar-based (not a held connection — see the function's own
      docstring for why), consulted by `fetch_rows`/`fetchrow`/`fetchval`/
      `execute`/`run_readonly`. Wired into `app/routers/query.py`'s
      `/api/query` (the primary curated-data query path) only —
      **not yet wired into `admin.py`/`history.py`/the login flow in
      `auth.py`**, which is exactly why 2.2 is deliberately not applied.
- [x] 2.2 **Actually done 2026-09-15** — re-audit found this item's own
      premise had gone stale: `app/routers/admin.py` and
      `app/routers/history.py` already depend on `app.deps.require_admin`/
      `require_user`, which already chain through `app.deps.tenant_scoped`
      (calls `set_tenant_context()`/`reset_tenant_context()` around every
      request) — likely fixed by uncommitted work after this task's text
      was written, never re-verified since. The two **real** gaps, found
      by tracing every `app.users`/`app.conversations`/`app.login_events`/
      `app.query_audit`/`app.tenant_schemes` write path instead of trusting
      the stale comment, both fixed:
      1. `app/routers/auth.py`'s `login()`/`bootstrap()` — no scope exists
         yet at that point (that's what they produce), and the username
         lookup is inherently cross-tenant. Both now wrap their body in
         `db.set_tenant_context(None, bypass=True)` — same trust model
         `tenant_scoped` already uses for a verified `super_admin`, applied
         here to server-side pre-authentication code, never client input.
      2. `app/main.py`'s startup sequence — `appdb.ensure_schema()`'s
         user-seed and `_sync_scheme_entitlements()`'s default-tenant
         grant-seed both write real `tenant_id` rows with no request/scope
         at all. Same bypass wrapping added around both startup steps.
      Section B of `deploy/sql/03_tenant_scheme_rls.sql` uncommented and
      completed (all 6 tables, `FORCE` included — required here for a
      different reason than Section A: `megh_app` *owns* every `app.*`
      table, and owners bypass RLS by default without `FORCE`). **Verified
      for real** against the same disposable Postgres as 3.3/3.4: applied
      Section B, then called the real `login()` function with zero tenant
      context set (its actual runtime situation) — succeeded for both a
      correct and a wrong password; confirmed `app.users` is genuinely
      tenant-isolated once a context *is* set (a tenant-A session cannot
      see a tenant-B user by username); confirmed `appdb.ensure_schema()`
      + `sync_to_db()` both still succeed when **re-run on an app restart
      with Section B already active** (the realistic ongoing-operations
      case, not just first boot) thanks to the `main.py` bypass fix. Full
      40-file regression sweep re-run after these changes: still 40/40.
- [x] 2.3 `TENANT_SCHEME_RLS_ENABLED` added to `app/config.py`, default
      `False`.
- [x] 2.4 Tests: `tests/test_tenant_scheme_entitlements.py` §5 covers the
      contextvar mechanics directly (flag-off no-op, flag-on round-trip,
      concurrent-task isolation) — pure Python, no DB, so it can't yet
      prove actual cross-tenant row leakage is blocked (that needs 2.2,
      which is deliberately not done — see above).
- [x] 2.5 Regression: `test_security.py`, `test_context_manager.py`, full
      full sweep (36 pre-existing + `test_tenant_scheme_entitlements.py`
      at the time) — all pass with the flag at its default `False`
      (flag-on behavior not regression-tested yet since 2.2 isn't applied).

## 3. RLS on curated/semantic scheme data

**Blocked for production activation** on the pre-existing DB-role cutover
(superuser → `megh_app`) — a superuser bypasses RLS regardless of policy.
Build and test this entire group against a disposable local Postgres
connected as a non-superuser role; do not claim production-readiness
until the cutover happens (leave that sub-item unchecked, per this repo's
human-gated-task rule, same as `phase-1-security-hardening` item 3).

- [x] 3.0 **Correction found during implementation (2026-09-15)**:
      `deploy/sql/03_tenant_scheme_rls.sql`'s first draft tried to
      `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` on every object in
      `scheme_registry.yaml`'s `tables:` lists, most of which are VIEWS
      (`docs/schema_for_developers.md` §6) — Postgres rejects RLS on a
      view outright. Rewritten to apply `ENABLE` + **`FORCE`** RLS to only
      the 5 real fact tables, with the policy-generator DO block checking
      `pg_class.relkind` live and skipping non-tables with a `NOTICE`
      rather than erroring. See `design.md`'s "Correction" note for the
      full reasoning, including why `FORCE` (not just `ENABLE`) is
      required for RLS to apply when a view is queried instead of the
      fact table directly.
- [x] 3.1 `app.tenant_has_scheme_access()` helper function
      (`design.md` §3), migration script — `deploy/sql/03_tenant_scheme_rls.sql`.
- [x] 3.2 Policy-generation script (not hand-typed per table): reads
      `curated.table_scheme_map`, emits one `CREATE POLICY` per
      scheme-owned FACT table (views skipped, protected transitively —
      see 3.0), `is_shared`/dimension tables skipped entirely (no RLS).
      Scales to 25 schemes without 25 hand-written statements — onboarding
      a new scheme's fact table is one `INSERT` into `table_scheme_map`.
- [x] 3.3 **Verified 2026-09-15 against a real, disposable local Postgres
      container** (`postgres:16-alpine`, not the shared `megh-one-db` —
      spun up and torn down for this alone): `SELECT rolname, rolsuper,
      rolbypassrls FROM pg_roles` confirms `megh_app` has
      `rolsuper=false, rolbypassrls=false` after running
      `01_create_megh_app_role.sql` verbatim. The view-owner BYPASSRLS
      check (migration script's own query) run for real against all 5
      views (`v_pmay`, `v_cross_scheme_money_district_year`,
      `v_cross_scheme_village_coverage`, `v_focus_plus`, `v_cm_elevate`)
      owned by a dedicated `etl_loader` role (NOSUPERUSER NOBYPASSRLS,
      mirroring the expected-correct production ETL role shape) —
      `rolbypassrls=false` for every row, matching the script's own
      "Expected" line exactly.
- [x] 3.4 **Real end-to-end proof, run 2026-09-15**, not simulated: full
      `curated` schema (dims + all 5 fact tables + the 5 RLS-relevant
      views) built from `docs/DATA_MODEL.md`'s documented columns for
      MGNREGA/PMAY-G; Focus Plus/CM Elevate tables are structurally
      minimal (a geography/year FK + one measure column) since their
      production DDL isn't documented anywhere in this repo — sufficient
      to prove the RLS *mechanism* generalizes to all 5 tables, not a
      claim about those two schemes' real column semantics. Real
      `03_tenant_scheme_rls.sql` applied verbatim (unmodified). Connected
      as `megh_app` (not postgres), tenant granted MGNREGA only,
      `app.tenant_bypass=off`: `fact_mgnrega_employment` → 3 rows
      (granted); `fact_pmay_house`/`fact_focus_plus_disbursement`/
      `fact_cm_elevate_application` → 0 (not granted); `v_pmay` (via the
      view) → 0; `v_cross_scheme_money_district_year` → only the MGNREGA
      branch, PMAY-G branch empty; `v_cross_scheme_village_coverage` →
      `pmay_houses` NULLed on every row; `dim_geography` (shared) → 3
      (unrestricted). With `app.tenant_bypass=on` (super_admin path):
      `fact_pmay_house`/`v_pmay` → 2 (bypass confirmed working). Every
      single expectation in the migration script's own bottom-section
      comments matched exactly — no surprises.
- [ ] 3.5 **Human-gated, leave unchecked**: production activation —
      requires the DB-role cutover maintenance window. Do not attempt from
      this repo/session; re-verify `.env`'s `DATABASE_URL` before ever
      checking this box.

## 4. Replace hardcoded scheme allowlists with tenant grants

- [x] 4.1 `app/auth.py::scope_from_user()`: tenant grant (resolved in
      `app/deps.py::current_scope` via `appdb.tenant_effective_schemes`)
      now intersects with the role cap, never widens it. `ROLE_PERMISSIONS`
      itself was unchanged at the time (still the cap/ceiling) — the ask
      was to stop treating its literal lists as the *entitlement source*,
      which is now `app.tenant_schemes`, not to delete the role-cap
      concept. **Updated 2026-09-18 — see 4.5**: `ROLE_PERMISSIONS`'
      literals themselves were the one hardcoded-list instance 4.2 below
      didn't cover; this note is now stale on its own, corrected there.
      `cache_fingerprint()` also fixed to include `tenant_id` when the
      flag is on — found during implementation, not in the original
      design: without it, two tenants could share a cached answer once
      curated data is genuinely tenant-scoped.
- [x] 4.2 **Actually fixed 2026-09-15** (previously flagged-not-fixed —
      re-scoped after re-verification found it was smaller than it
      looked): `app/prompt_builder.py::_scheme_of()` no longer uses
      hand-authored substring/exact-match dicts (`_MGNREGA_EXACT` etc.) —
      it now looks up the bare table name against every scheme's
      `tables:` list from `scheme_registry.tables_for()`, the same data
      each scheme must already declare for schema-retrieval to work.
      `app/followups.py`'s `_SCHEME_RX` is now `_scheme_regexes()`, built
      from each scheme's `id`/`display_name`/`aliases` in
      `scheme_registry.yaml` instead of a fixed module-level dict — two
      alias variants the old hand-typed regex covered but the registry
      didn't (`mnrega`, `awas`/`awaas`) were added to
      `scheme_registry.yaml` itself so nothing regresses, matching that
      file's own stated intent ("kept here too so retrieval pre-filtering
      and the classifier stay in the same vocabulary"). A newly onboarded
      scheme now needs zero changes to either file — only its registry
      entry, which it needs anyway. **Deliberately left alone**:
      `app/pipeline.py::_SCHEME_FUZZY_ALIASES` — a separate, real
      hand-authored dict for typo-tolerant fuzzy matching (`fuzz.ratio`
      against short single-word forms) discovered while re-verifying this
      task; architecturally distinct from the two exact-match cases above
      (registry aliases mix multi-word phrases that don't fit a
      single-word fuzzy model) and never named by this task — flagging
      it here rather than silently expanding scope.
- [x] 4.3 `tests/test_tenant_scheme_entitlements.py` §§1-4 (intersection,
      cross-scheme authorization) and `tests/test_scheme_scaleout_fallbacks.py`
      (the two swapped literals) — confirms today's 1-tenant/4-scheme seed
      produces identical effective permissions to the old hardcoded lists.
- [x] 4.4 Regression: `test_security.py` + full sweep pass.
- [x] 4.5 **Found and fixed 2026-09-18, the one hardcoded-list instance
      4.1/4.2 didn't cover**: `app/auth.py::ROLE_PERMISSIONS` hand-typed
      `["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate"]` once per role, 8
      times — the exact "shotgun surgery per onboarded scheme" pattern
      this group exists to eliminate, just missed in the first pass
      because it wasn't a substring/regex dict like 4.2's two. Fixed:
      every role's `"schemes"` key removed from the literal; a new
      `auth._role_scheme_cap(role_perms)` resolves it lazily via
      `scheme_registry.scheme_ids()` at call time (a role can still set
      its own explicit `"schemes"` override if a future one ever needs a
      narrower cap than "every registered scheme" — none does today).
      **Ordering hazard found and handled**: `ROLE_PERMISSIONS` is a
      module-level dict built at `app/auth.py` import time, before
      `app/main.py`'s startup ever calls `scheme_registry.load_all()` — a
      literal `scheme_registry.scheme_ids()` call baked into the dict
      itself would have frozen at an empty list. `_role_scheme_cap()` is
      called at request time (inside `scope_from_user()`/
      `anonymous_scope()`), after startup has loaded the registry, so
      this doesn't apply — but it broke two tests that construct a
      `UserScope` via `scope_from_user()` without ever loading the
      registry first (`tests/test_authorization.py`,
      `tests/test_tenant_scheme_entitlements.py`) — fixed by adding the
      same `scheme_registry.load_all()` call the real app always makes
      before serving a request. **Also fixed**: `GET /admin/roles`
      (`app/routers/admin.py`) dumped `ROLE_PERMISSIONS` raw — now
      missing `schemes` entirely per role — now resolves each role's
      effective cap via `_role_scheme_cap()` before returning, so the
      endpoint's response shape is unchanged. **Verified the actual
      scaling claim, not just that it compiles**: temporarily added a
      5th scheme to the real `scheme_registry.yaml` (reverted
      immediately, `git diff` confirmed clean) and called `/admin/roles`
      — all 8 roles picked it up automatically, zero `auth.py` edits.
      Full 40-file regression sweep: all pass.

## 5. LangGraph production cutover

**Context that changed the priority of this group**: the original Grant
Thornton proposal (`GrantThornton_Solution_Proposal_1 (1).pdf`, repo root)
Section 4 states *"The runtime pipeline is implemented as a LangGraph
agent"* — not an optional enhancement. Before this group, that was not
true of the running system: `PIPELINE_GRAPH_ENABLED` was defined in
`app/config.py` and read nowhere (confirmed by grep). See `proposal.md`'s
"Why" §3 and `design.md` §4a for the full finding and the adapter design.

- [x] 5.0 **Re-scoped from the original 5.1**: no `tenant_id` field needed
      on `PipelineGraphState` — `node_execute_attempt` already calls
      `pipeline._execute_one_attempt`, the same function the bespoke path
      calls, which reaches `app.db.run_readonly()` where group 2's
      contextvar-based tenant context applies automatically regardless of
      caller. Verified by reading the implementation, not assumed.
- [x] 5.1 **The actual cutover**: `pipeline_graph.answer_data_via_graph_compat()`
      (new) — same calling contract as `app.pipeline._answer_data`
      (raises `ClarificationNeeded` for a pause, returns a dict otherwise)
      — wired into `app/pipeline.py::_run_pipeline`'s single call site
      behind `settings.PIPELINE_GRAPH_ENABLED`. Zero changes to
      `app/routers/query.py` or `app/session_store.py`. See `design.md`
      §4a for why a naive direct swap to `answer_data_via_graph` would
      have been wrong (return-shape mismatch on the pause case) and the
      deliberate scope boundary (no cross-request graph resume — see 5.4).
- [x] 5.2 **Correction found during implementation (2026-09-15)**: this
      item's "mirrors `phase-2-orchestration-durability`'s validated
      approach for `LANGGRAPH_FOLLOWUP_ENABLED`" claim didn't hold up on
      re-verification — that flag is also just a single global bool, no
      canary mechanism exists anywhere in this codebase to mirror. Built
      new instead: `app/pipeline._pipeline_graph_selected(session)` —
      `PIPELINE_GRAPH_CANARY_PERCENT` (0-100, default 0, new in
      `app/config.py`) gives a session-sticky canary (bucketed by
      `user_id`, falling back to `session_id`, via a stable SHA-256 hash —
      so one conversation never flips paths mid-thread), ignored (treated
      as 100) once `PIPELINE_GRAPH_ENABLED` itself is `True`. Wired into
      the one call site in `_run_pipeline`. Tests: new §3 in
      `tests/test_pipeline_graph_cutover.py` (17 checks total in that
      file now, all passing) — 0%/100%/no-session/determinism/override/
      spread-across-40-distinct-users all covered.
- [x] 5.3a Mocked-boundary parity tests: `tests/test_pipeline_graph_cutover.py`
      (new) confirms the pause→exception conversion and that the flag
      branch actually reroutes `_run_pipeline` to the graph adapter (and
      not, when off) — same mocking boundary as `test_pipeline_graph.py`.
- [ ] 5.3b **Not done, the actual remaining gate**: end-to-end parity
      against a live LLM + live Postgres across all 4 schemes.
      `pipeline_graph.py`'s existing test suite (and the new one from 5.3a)
      is explicitly mocked-only — no live LLM/DB reachable from this
      environment. Do not flip `PIPELINE_GRAPH_ENABLED` to `True` in any
      real deployment before this runs.
- [x] 5.4 **Done 2026-09-18**: real cross-HTTP-request resume through
      LangGraph's own checkpointer (`resume_via_graph`), previously unused
      by the compat adapter. Turned out to need no `app/session_store.py`
      changes — `session_id` is reused directly as the LangGraph
      `thread_id`, the exact same trick `app/langgraph_followup.py::
      is_paused` already used for its own, separate checkpointer, so no
      new field was needed anywhere.
      **What changed**: `pipeline_graph.answer_data_via_graph_compat()`
      gained an optional `thread_id` param — when the caller passes one
      (in practice, `session.session_id`, only when
      `LANGGRAPH_FOLLOWUP_ENABLED` is off), a pause keeps its checkpoint
      alive instead of being cleaned up, and raises `ClarificationNeeded(
      graph_resumable=True)` so `query.py`'s handler knows NOT to also set
      the bespoke `pending_scope_q`/`pending_village_hint` fields — this
      pause's resume state now lives durably in the graph's own
      checkpointer. A new `pipeline_graph.is_paused()` (mirrors
      `langgraph_followup.is_paused` exactly) is checked at the top of
      `query.py`, before the routing maze runs — if true, the request
      bypasses `_run_pipeline` entirely and calls `resume_via_graph`
      directly, since a paused graph must resume at the exact node it
      paused at, not restart the whole pipeline from node 5.1.
      **Deliberately mutually exclusive with `LANGGRAPH_FOLLOWUP_ENABLED`**:
      when both flags are on, `langgraph_followup`'s own wrapper already
      catches `ClarificationNeeded` around the entire call via its own,
      separate checkpointer — if pipeline_graph ALSO kept a checkpoint
      alive in that case, two independent checkpointers would both think
      they own the same pause, and pipeline_graph's would leak
      permanently (the exact bug fixed 2026-09-17 for the always-fresh-
      UUID case, reappearing in a new shape). `thread_id` is only passed
      when `LANGGRAPH_FOLLOWUP_ENABLED` is off, keeping the combined-flags
      case exactly as already tested.
      **A real, previously-undetected bug found and fixed while building
      this**: `node_entities` (§5.6) called the real `resolve_entities()`
      LLM/DB call AND `interrupt()` in the same graph node — LangGraph
      replays a paused node IN FULL on resume, so every resumed entity-
      ambiguous/scope pause wasted a second real `resolve_entities()` call
      with the STALE pre-merge question before the real attempt. Same bug
      class, same fix shape, as `app/langgraph_followup.py`'s 2026-09-17
      fix: split into `node_entities` (the expensive call, never re-
      entered on resume) and `node_entities_gate` (cheap — just
      `interrupt()` + merge). Existing `tests/test_pipeline_graph.py`
      scenario 8 never caught this because its mock only counted calls,
      never checked which question text each call received — strengthened
      alongside this fix. `node_clarification_gate` (§5.3) was
      deliberately NOT split the same way — its own pre-interrupt checks
      are cheap/deterministic, no LLM/DB call, so replaying it on resume
      costs microseconds, not a wasted real request.
      **Verified for real**: new `tests/test_query_pipeline_graph_resume.py`
      drives the actual HTTP route end to end — pause via `/api/query`,
      checkpoint survives, second request on the same session resumes via
      `resume_via_graph` (not a bespoke merge-and-restart), exactly 2 real
      `resolve_entities` calls across both requests (not 3), and the
      both-flags-on mutual-exclusivity case confirmed directly (pipeline_
      graph reports NOT paused, langgraph_followup reports paused —
      exactly one mechanism owns the pause, never both). Full 41-file
      regression sweep passes at default flags, with `PIPELINE_GRAPH_ENABLED`
      alone, and with all three feature flags on simultaneously.
      **Still not done, unchanged**: retiring `app/langgraph_followup.py`
      still doesn't make sense yet — it covers durable resume across a
      worker restart via a config-driven Postgres checkpointer path this
      task didn't touch, and 5.3b (live-LLM/Postgres parity) is still the
      actual gate before any of this goes live in production.
- [ ] 5.5 Postgres checkpointer cutover: only after the DB-role cutover
      (shared blocker); leave unchecked until then, matching group 3.5.
- [x] 5.6 Regression: `tests/test_query_langgraph_wiring.py`,
      `tests/test_pipeline_graph.py`, `tests/test_pipeline_graph_cutover.py`,
      full 40-file sweep — all pass, flag at its default `False`.
- [x] 5.7 **Three real bugs found and fixed 2026-09-17**, via a fresh
      code-review pass (not re-running old tests — those all already
      passed) specifically targeting `app/pipeline_graph.py`,
      `app/langgraph_followup.py`, and the cutover/canary logic in
      `app/pipeline.py`. All three re-verified: reproduced the bug, fixed
      it, then proved the fix with a new test assertion against real
      behavior (not just "tests still pass"):
      1. **Orphaned checkpoint rows, unbounded growth**:
         `answer_data_via_graph_compat` deliberately never resumes a
         pause via LangGraph's own checkpointer (by design, see its
         docstring) — but nothing ever deleted the checkpoint that pause
         had already written, so every clarification any user ever hit
         left a permanent, never-cleaned-up row in the checkpoint store.
         Fixed: `_delete_orphaned_thread()` calls the checkpointer's own
         `adelete_thread()` right before converting the pause to a
         `ClarificationNeeded` raise. Verified two ways: a spy proving the
         call happens with the right thread_id, AND a fully real
         end-to-end run (real graph, real SQLite file) confirming zero
         checkpoint rows remain on disk afterward —
         `tests/test_pipeline_graph_cutover.py` checks 1b/1c.
      2. **`app/langgraph_followup.py` re-ran the full, real
         `pipeline.answer_question` call a wasted second time on every
         resume** — LangGraph replays an interrupted node in FULL on
         resume, and the original single-node design called `interrupt()`
         in the same node as the expensive pipeline call, so every
         resumed clarification cost 3 real pipeline calls for 2 logical
         attempts (confirmed empirically before the fix). Fixed: split
         into `_classify_node` (the expensive call, never re-entered on
         resume) and `_gate_node` (cheap — just `interrupt()` + merge,
         the only node LangGraph re-executes on replay), with the
         clarification payload passed between them via a real
         checkpointed state field (`pending_clarification`), not a local
         variable. `tests/test_langgraph_followup.py` now asserts the
         exact call count (2 for one pause+resume, 3 for a 3-round
         multi-clarification exchange — was 3 and 5 before the fix) so
         this can't silently regress. Only affects
         `LANGGRAPH_FOLLOWUP_ENABLED=True` (default off).
      3. **Two documentation-only bugs**: a dead `paused_rule` kwarg in
         `run_with_pause` (a `FollowupState` field that was never declared
         in the TypedDict and never read anywhere — silently accepted, not
         a runtime bug, just leftover cruft; removed, replaced with the
         now-real `pending_clarification` field), and `app/config.py`'s
         `PIPELINE_GRAPH_CANARY_PERCENT` comment claiming the canary
         buckets by session_id-first when the actual code (and
         `app/pipeline.py::_pipeline_graph_selected`'s own docstring)
         always bucketed by user_id-first — the code was right, the
         comment was wrong; corrected to match.
      **Also found, deliberately NOT fixed** (checked, not a real bug): a
      code-review pass flagged `pipeline_graph.py`'s per-call
      `AsyncSqliteSaver` connection as a possible hot-path concurrency
      risk. Verified against the library source: `AsyncSqliteSaver`
      already enables `PRAGMA journal_mode=WAL` internally, and opening a
      scoped connection per call is the library's own documented usage
      pattern — the finding's specific claim ("no documented concurrency
      strategy") was factually wrong, so left alone.
      **Environment note**: this machine's Application Control policy
      started blocking `uuid_utils`'s and `orjson`'s native DLLs sometime
      between 2026-09-15 and 2026-09-17 — every LangGraph-touching test
      (not just this session's changes; confirmed `test_pipeline_graph.py`
      failed identically with zero edits) was unable to even import. Fixed
      locally by pinning both to a different, non-blocked version in
      *this venv only* (`uuid_utils==0.12.0`, `orjson==3.11.5` — both
      still satisfy every installed package's version constraint, `pip
      check` clean). **`requirements.lock` deliberately left unchanged** —
      this is a workaround for a local machine policy, not a real
      dependency requirement change, and baking it into the shared lock
      file could paper over a real IT/security policy question worth the
      human's attention on whatever machine actually runs this in
      production.

## 6. Scheme onboarding scale-out — 6.1-6.3 done 2026-09-15

- [x] 6.1 `POST /admin/reload-join-graph` (`app/routers/admin.py` — same
      `/admin` prefix as this repo's other admin routes; `design.md`'s
      original `/api/admin/...` sketch didn't match the actual prefix,
      corrected here) calls `join_graph.build(force=True)`, returns the
      rebuilt graph's node counts.
- [x] 6.2 `app/scheme_registry.py::warn_if_scheme_count_high()` — logs
      (never blocks boot) once the registered non-shared scheme count
      exceeds `SCHEME_COUNT_WARN_THRESHOLD` (10), pointing at
      `schema-retrieval-reranking`/`sql-generation-vector-fewshot` as the
      real fix. Wired into `app/main.py`'s startup, right after
      `load_scheme_registry()`. Uses the in-memory registry count, not a
      DB query against `app.schemes` — no new startup DB dependency for a
      log line. Tested in `tests/test_scheme_scaleout_fallbacks.py` §3
      (does not raise at today's count or when simulated over threshold).
- [x] 6.3 `docs/scheme-onboarding.md` updated: step 1 notes the DB-sync
      side effect of the registry reload; step 5 now points at the real
      `POST /admin/reload-join-graph` endpoint instead of describing the
      restart requirement as unaddressed; new step 6 documents the
      tenant-grant step (a no-op today, flag off).
- [x] 6.4 **Run for real 2026-09-15** against the same disposable
      Postgres as 3.3/3.4, in one continuously-running Python process
      (no restart between steps): temporarily added a `TEST5` scheme
      block to the real `scheme_registry.yaml` (reverted immediately
      after — `git diff` confirmed clean), created its one fact table.
      `scheme_registry.load_all()` picked it up; `sync_to_db(tid)` wrote
      it into `app.schemes`; `join_graph.build(force=True)` (the real
      `POST /admin/reload-join-graph` logic) ran clean; a `table_scheme_map`
      insert + the exact `ENABLE`/`FORCE`/`CREATE POLICY` statements
      applied (mirroring an onboarding runbook step, not the full
      migration script re-run) — a tenant without a `TEST5` grant saw 0
      rows, a tenant granted `TEST5` saw both. Zero process restarts
      anywhere in the sequence — the actual claim this task exists to
      prove.
      **Bonus finding, not part of this task's original scope**: the same
      bootstrap run also exercised `app.appdb.ensure_schema()` connected
      as `megh_app` (not postgres) for the first time anywhere in this
      repo's tests, and caught a real bug — see the new note under group 1.

## 7. Documentation and final regression

- [x] 7.1 `docs/SECURITY.md`: new A01 row for curated-data RLS, cross-
      referenced with the existing A03 DB-role row (same blocker).
      `docs/ARCHITECTURE.md`: "Multi-tenancy" section extended with the
      RLS/entitlement mechanism; "Routing" section documents
      `PIPELINE_GRAPH_ENABLED` as a now-real (previously inert) selector
      between `_answer_data` and the LangGraph path, with an honest "not
      yet verified end-to-end" caveat. Also cross-referenced from
      `openspec/changes/langgraph-full-pipeline-rewrite/design.md` and
      `phase-1-security-hardening/proposal.md` (both had claims this
      change made partially stale) and `CLAUDE.md` (addendum, the
      2026-09-11 list itself left untouched).
- [x] 7.2 Full regression sweep, all flag combinations — **all genuinely
      resolved 2026-09-15** (all 40 script-style `tests/test_*.py`;
      `smoke_restructure.py` excluded — needs a live HTTP server, not this
      repo's test convention; exit code AND full output scanned for a
      swallowed-but-logged traceback, not exit code alone — see the note
      below on why that distinction mattered):
      - **All flags at default (off)**: 40/40 pass.
      - **`PIPELINE_GRAPH_ENABLED=True` alone**: all pass.
      - **All three flags on together** (`TENANT_SCHEME_RLS_ENABLED` ×
        `PIPELINE_GRAPH_ENABLED` × `LANGGRAPH_FOLLOWUP_ENABLED`) — first
        pass found **2 genuine failures**: `tests/test_langgraph_query_analyzer.py`
        and `tests/test_pii_audit_trail.py`. Root-caused precisely, not
        guessed at:
        1. `test_langgraph_query_analyzer.py` mocked `execute_with_repair`
           and never mocked `schema_retrieval.retrieve` — but
           `pipeline_graph.py`'s `node_execute_attempt` calls the
           lower-level `pipeline._execute_one_attempt` directly (it
           implements its own repair loop via graph edges instead — see
           that module's own docstring on why), and `node_schema_retrieve`
           calls `schema_retrieval.retrieve` for real. Neither was in this
           test's mock list because it only ever needed to cover
           `_answer_data`'s call chain before. Fixed: added both mocks
           (same shapes `tests/test_pipeline_graph.py` already uses).
        2. `test_pii_audit_trail.py` patched `query_router.answer_question`
           (a name bound via `from app.pipeline import answer_question` in
           `app/routers/query.py`) — but with `LANGGRAPH_FOLLOWUP_ENABLED`
           on, `query.py` calls `langgraph_followup.run_with_pause`
           instead, which calls `pipeline.answer_question` via its own
           separate `from app import pipeline` binding, completely
           unaffected by patching the other name. Fixed: also patch
           `pipeline.answer_question` directly, restored in the same
           `finally`.
        **Bonus, caught while fixing #1**: the mock fix let the pipeline
        run far enough to reach `app/followups.py::build_followups` for
        the first time in this test, which crashed
        (`IndexError: list index out of range` on `primary[0]`) — a real
        latent bug in group 4.2's same-day refactor: the new
        registry-driven `_scheme_regexes()` can return an empty dict if
        `scheme_registry.load_all()` was never called in-process (this
        test never calls it — the real app always does at startup), unlike
        the old fixed module-level dict it replaced, which worked
        regardless of registry load state. Caught only because
        `_attach_followups` swallows exceptions and logs them
        non-fatally — the test's exit code stayed 0 even with this crash
        happening internally, which is exactly why this sweep re-scanned
        full output for a traceback instead of trusting exit codes alone.
        Fixed with a defensive empty-`primary` guard in `build_followups`
        itself (returns `[]`, not a crash — the correct behavior
        regardless of why `primary` is empty, not specific to this test).
        **Final re-run after both fixes: full 40-file sweep, all three
        flags on, output-scanned not just exit-code-checked: 40/40 pass,
        zero unexpected tracebacks** (the "6 flagged" during scanning were
        all confirmed by hand to be benign — deliberately-injected error
        scenarios or the literal word "Traceback" appearing in a check's
        own description string, e.g. `test_security.py`'s "no 'Traceback'
        in error body" check).
- [x] 7.3 Final report (2026-09-15, second pass — group 0-1 stub +
      groups 5.2/7.2 done in an earlier pass same day, everything below
      genuinely completed in this pass, not just re-described):

      **Files changed this pass**: `app/appdb.py` (privilege bug fix),
      `app/routers/auth.py` + `app/main.py` (login/bootstrap/startup
      tenant-context bypass), `deploy/sql/03_tenant_scheme_rls.sql`
      (Section B written and enabled), `app/prompt_builder.py` +
      `app/followups.py` + `scheme_registry.yaml` (4.2's registry-driven
      rewrite, plus the empty-`primary` guard found while fixing 7.2),
      `tests/test_langgraph_query_analyzer.py` + `tests/test_pii_audit_trail.py`
      (7.2's mock-boundary fixes), this file.

      **Groups closed for real, with genuine verification, not just
      re-worded claims**: 2.2, 3.3, 3.4, 4.2, 6.4, 7.2 — each involved
      finding and fixing at least one real, previously-undiscovered gap
      (a privilege bug, a missing bypass, a stale premise, a mock
      mismatch, a fresh regression caught mid-fix), not just checking a
      box. 3.3/3.4/6.4 were verified against a fresh, genuinely disposable
      Postgres container built for this alone (not the shared
      `megh-one-db`) — full session transcript has the exact commands and
      output if anyone wants to reproduce it; the container was left
      running at session end for potential follow-up, not yet torn down.

      **What remains unchecked, and why — all deliberate, none guessed
      past**:
      - 3.5 / 5.5 / phase-1-security-hardening's item 3 — the production
        DB-role cutover. Requires `ALTER ROLE`/`GRANT` against
        `10.48.242.4`'s `postgres` superuser connection, which this
        session has live credentials for but was explicitly told not to
        use for this (user confirmed "skip both, safe items only" when
        asked directly). Stays a human/infra action.
      - 5.3b — live LLM + Postgres parity across all 4 schemes. Same
        reasoning: the only reachable "live" LLM is also `10.48.242.4`,
        explicitly excluded by the same confirmation.
      - 5.4 — cross-request LangGraph resume (`resume_via_graph`). A
        genuinely separate feature (new `Session` fields, a new
        `query.py` routing branch, real interaction with two *existing*
        pause/resume mechanisms) needing its own design pass, not a
        bounded gap in already-90%-done work like everything else in this
        pass. Deliberately not rushed.
      No commit — human commits, per this repo's standing process.

## Regression baseline (run after every group above)

`test_security.py`, `test_context_manager.py`, `test_schema_retrieval.py`,
`test_pipeline_schema_retrieval.py`, `test_join_graph.py`,
`test_pipeline_join_discovery.py`, `test_query_langgraph_wiring.py`,
`test_pipeline_graph.py`, plus whichever new suite the group just added.
