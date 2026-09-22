# Design: Tenant/Scheme RLS, LangGraph Cutover, Scale-Out

Companion to `proposal.md`. Sketches the concrete mechanism so review can
catch design mistakes before `tasks.md` work starts. Nothing here is
final — flagged decision points need explicit sign-off.

## 1. Entitlement schema

```sql
-- app.schemes: canonical scheme identity, DB-backed (today this only
-- lives in-memory, loaded from scheme_registry.yaml at startup).
CREATE TABLE app.schemes (
    scheme_id    TEXT PRIMARY KEY,        -- matches scheme_registry.yaml's `id` (e.g. 'MGNREGA')
    display_name TEXT NOT NULL,
    is_shared    BOOLEAN NOT NULL DEFAULT false,  -- mirrors `shared:` in scheme_registry.yaml
    is_active    BOOLEAN NOT NULL DEFAULT true,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- app.tenant_schemes: which tenant can see which scheme's data.
CREATE TABLE app.tenant_schemes (
    tenant_id   BIGINT NOT NULL REFERENCES app.tenants(tenant_id),
    scheme_id   TEXT NOT NULL REFERENCES app.schemes(scheme_id),
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    granted_by  BIGINT REFERENCES app.users(user_id),
    PRIMARY KEY (tenant_id, scheme_id)
);

-- curated.table_scheme_map: which curated table belongs to which scheme,
-- so RLS policies are generated/driven by data, not hand-written per
-- table (the thing that would NOT scale to 25 schemes if done manually).
CREATE TABLE curated.table_scheme_map (
    table_schema TEXT NOT NULL,
    table_name   TEXT NOT NULL,
    scheme_id    TEXT REFERENCES app.schemes(scheme_id),  -- NULL for shared tables
    PRIMARY KEY (table_schema, table_name)
);
```

`scheme_registry.yaml` stays the human-authored source for onboarding (per
`docs/scheme-onboarding.md`'s existing step 1), but the admin reload
endpoint (`POST /api/rag/reload-scheme-registry`) is extended to also
upsert `app.schemes` and `curated.table_scheme_map` from the YAML's
`tables:`/`shared:` fields — one onboarding action populates both the
in-memory registry (existing behavior) and the DB-enforced mapping (new).
This directly answers the "25 schemes" scale concern: onboarding scheme
#25 is the same one YAML edit + reload as scheme #5, not a hand-written
`CREATE POLICY` statement.

**Resolved** (`tasks.md` 0.1, by proceeding with this section's own
recommendation rather than separate sign-off): effective access =
`tenant_schemes ∩ role_scheme_cap` — the role stays a ceiling
(`ROLE_PERMISSIONS`'s lists are unchanged), the tenant grant only narrows
it. Implemented in `app/auth.py::scope_from_user`, tested in
`tests/test_tenant_scheme_entitlements.py` §§1-2.

## 2. Session-GUC mechanism (RLS enforcement point)

Postgres RLS policies read session state via `current_setting(name, true)`
(the `true` = don't error if unset). The app must set this per logical
request, not per pooled connection (connections are reused across
tenants).

- `app/db.py`'s query-execution helper wraps each request's DB work in an
  explicit transaction and issues `SELECT set_config('app.current_tenant_id', $1, true)`
  (the `true` = transaction-local, auto-resets — critical for a pooled
  connection reused by the next request) as the **first** statement,
  before any query the request itself issues.
- `UserScope` (already resolved per-request in `app/auth.py`) is the
  source of the tenant id — no new resolution logic needed, just threading
  it into the DB call.
- A second local GUC, `app.tenant_bypass`, is set to `'on'` **only** when
  `UserScope.role == 'super_admin'` (server-resolved, never client input)
  — used by cross-tenant admin list views (`conversation_store.admin_list_conversations`
  etc.) instead of removing RLS from those tables. `tenant_admin` does
  **not** get this bypass on curated data — per the "Why" section's
  finding that `tenant_admin` bypassing all query checks today was itself
  a gap, not a feature to preserve for curated data. `tenant_admin`'s
  cross-tenant admin-UI visibility into `app`-schema tables (its own
  tenant only) is unaffected.

## 3. RLS policies

**App schema** (straightforward — `tenant_id` column exists on every
table already):

```sql
ALTER TABLE app.conversations ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON app.conversations
    USING (
        tenant_id = current_setting('app.current_tenant_id', true)::bigint
        OR current_setting('app.tenant_bypass', true) = 'on'
    );
```
Repeated for `app.users`, `app.login_events`, `app.conversation_turns`,
`app.query_audit`, `app.tenant_schemes` (a tenant can only see its own
grants, `super_admin` sees all via bypass).

**Correction (found during implementation, 2026-09-15) — RLS cannot be
enabled on a VIEW.** Every curated object the app actually names in
generated SQL (`v_employment`, `v_pmay`, `v_cross_scheme_money_district_year`,
etc. — see `docs/schema_for_developers.md` §6, "Views — query these, not
the raw facts") is a VIEW over one or more real fact tables, and Postgres
rejects `ALTER TABLE viewname ENABLE ROW LEVEL SECURITY` outright ("is not
a table"). The actual mechanism: enable + **`FORCE`** RLS on the 5 real
fact tables only (`fact_mgnrega_employment`, `fact_mgnrega_expenditure`,
`fact_pmay_house`, `fact_focus_plus_disbursement`,
`fact_cm_elevate_application`) and rely on Postgres applying that
transparently to any view built over them. `FORCE ROW LEVEL SECURITY` is
not optional here: row security on a table accessed *through a view* is
evaluated under the **view owner's** privileges, and table owners bypass
RLS on their own tables by default — since the views and their underlying
facts are almost certainly owned by the same (non-`megh_app`) role, `FORCE`
is what makes RLS apply even to that owner. `FORCE` still loses to an
owner role with the `BYPASSRLS` attribute — that can only be checked
against a live database (see `deploy/sql/03_tenant_scheme_rls.sql`'s
verification queries), not asserted from this repo. This also resolves the
two cross-scheme views cleanly: `v_cross_scheme_money_district_year` is a
`scheme_code`-tagged UNION ALL over the MGNREGA/PMAY-G facts, and
`v_cross_scheme_village_coverage` is a per-village join of both — with RLS
on the two underlying facts, a tenant missing one scheme's grant
transparently gets that branch/column empty or NULL'd, never the other
scheme's real data, with **no bespoke per-view policy needed**.

**Curated/semantic scheme data** — no `tenant_id` column exists or should
be added (the underlying rows aren't tenant-owned; multiple tenants can
share access to the same scheme). Policy checks the entitlement table via
a helper function instead of a column, applied to the fact tables above
(not the views):

```sql
CREATE FUNCTION app.tenant_has_scheme_access(p_scheme_id TEXT)
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER AS $$
    SELECT current_setting('app.tenant_bypass', true) = 'on'
        OR EXISTS (
            SELECT 1 FROM app.tenant_schemes
            WHERE tenant_id = current_setting('app.current_tenant_id', true)::bigint
              AND scheme_id = p_scheme_id
        );
$$;

-- One policy per scheme-owned FACT table, generated from
-- curated.table_scheme_map during migration (a script, not 21 hand-typed
-- statements once scheme count grows) — e.g. for fact_mgnrega_employment
-- (scheme_id = 'MGNREGA'). FORCE is not optional — see the correction
-- note above for why ENABLE alone doesn't apply when queried via a view.
ALTER TABLE curated.fact_mgnrega_employment ENABLE ROW LEVEL SECURITY;
ALTER TABLE curated.fact_mgnrega_employment FORCE ROW LEVEL SECURITY;
CREATE POLICY scheme_access ON curated.fact_mgnrega_employment
    USING (app.tenant_has_scheme_access('MGNREGA'));
```

`shared: true` tables (`dim_geography`, `dim_year`, etc.) get **no** RLS
enabled — always visible, matching `scheme_registry.yaml`'s existing
`shared` semantics exactly.

**Flag-off fallback — resolved** (`tasks.md` 0.2): option (a). With
`TENANT_SCHEME_RLS_ENABLED=false`, `app/db.py` never issues the
`set_config` call (confirmed: `set_tenant_context()` returns a no-op token
when the flag is off, see `tests/test_tenant_scheme_entitlements.py` §5),
**and** the RLS migration itself
(`deploy/sql/03_tenant_scheme_rls.sql`) is a standalone script never run
automatically by app startup — so flag-off means "this mechanism doesn't
exist yet in that database" everywhere, not "exists but silently denies
everything because the GUC is unset." Option (b) (an escape-hatch GUC on
the policies themselves) was rejected as unneeded extra surface, per the
original recommendation here.

## 4. LangGraph cutover

- `PIPELINE_GRAPH_ENABLED` flips per-request (not global) initially — a
  request-level dice roll or admin-only header for staged canary, mirroring
  how `LANGGRAPH_FOLLOWUP_ENABLED` was validated (`phase-2-orchestration-durability/tasks.md`
  group 10: flag-off byte-identical, flag-on found and fixed a real bug
  before wider rollout). **Not yet implemented** — the flag today is a
  single global on/off, no per-request canary mechanism.
- **Correction from this design's first draft**: `PipelineGraphState` does
  **not** need a `tenant_id` field, and `node_execute_attempt` needs no
  RLS-specific change at all. It calls `pipeline._execute_one_attempt` —
  the exact same function the bespoke path calls — which reaches
  `app.db.run_readonly()`, and §2's session-GUC mechanism there is a
  `contextvars.ContextVar` set once per HTTP request
  (`app/routers/query.py`'s outer wrapper), not an explicit parameter any
  caller has to thread through. Whichever code path (`_answer_data` or
  `pipeline_graph`) ends up calling `run_readonly()` picks up the same
  request-scoped tenant context automatically. Confirmed by reading
  `node_execute_attempt`'s implementation, not assumed.
- Checkpointer: switch `PIPELINE_GRAPH_CHECKPOINTER_DSN` to a real Postgres
  DSN only once the DB-role cutover (shared blocker, see proposal.md) is
  resolved — until then, SQLite checkpointing is fine for a canary
  rollout since checkpoint state is process-local durability, not a
  security boundary. **Not yet done** — still SQLite by default.
- `app/langgraph_followup.py` retirement: once `pipeline_graph.py` is
  confirmed to handle all 3 pause types (`scope-not-specified`,
  `year-not-specified`, `entity-ambiguous`) at parity, delete the
  `LANGGRAPH_FOLLOWUP_ENABLED` flag and its call sites in
  `app/routers/query.py:10,133,141,143` in the same task group that
  finishes the cutover — not left running in parallel indefinitely.
  **Not yet done** — both flags/modules still coexist; see §4a below for
  why the compat adapter implemented so far doesn't yet establish full
  parity with `langgraph_followup.py`'s pause handling (it establishes
  parity with the *bespoke* `_answer_data` path, which is the thing that
  actually needed replacing per the GT proposal's Section 4).

## 4a. LangGraph cutover — the actual adapter (implemented 2026-09-15)
The naive approach — swap `_run_pipeline`'s `_answer_data(...)` call for
`pipeline_graph.answer_data_via_graph(...)` directly — is wrong. Their
return contracts differ on the one case that matters most: `_answer_data`
raises `ClarificationNeeded` for a pause; `answer_data_via_graph` *returns*
`{"paused": True, "clarification": {...}, "thread_id": ...}`. A naive swap
would make every pause-eligible clarification silently fall through
`_run_pipeline`'s `except ClarificationNeeded` handling and reach
`app/routers/query.py` as if it were a normal, successful answer —
missing `answer`/`sql`/`data` fields, a broken response for the frontend.

**The fix**: `pipeline_graph.answer_data_via_graph_compat()` — same
signature as `_answer_data`, and it converts a paused result straight back
into a `ClarificationNeeded` raise (`rule`, `question`, `options`,
`village_hint` all round-tripped through the interrupt payload, which
needed one addition — `_pause()` now includes `village_hint` in the dict
passed to `interrupt()`, previously only carried in the graph's internal
`update` dict, unreachable from outside a resumed graph run).

**Deliberate scope boundary, not an oversight**: this adapter never calls
`resume_via_graph`, and each call to `answer_data_via_graph` gets a fresh,
throwaway `thread_id` — no cross-HTTP-request resumability through
LangGraph's own checkpointer is attempted. Instead, a pause becomes a
`ClarificationNeeded` exception exactly like the bespoke path, and
`_run_pipeline`'s existing (already tested, unmodified) reply-merge logic
— `session.state.pending_scope_q`/`pending_village_hint`, the chip-resume
detection, `_reply_abandons_scope_pause` — handles the next turn by
building a new, merged question string and calling the adapter *fresh*.
The graph's own `interrupt()`/checkpointer machinery is still genuinely
exercised, just scoped to within one call (its `_route_restart` conditional
edges looping back to node 5.1 on a resume within the same graph
invocation) rather than across requests.

Why this boundary, not the "more complete" version: a real cross-request
LangGraph resume would require `app/routers/query.py` and
`app/session_store.py` to track a `thread_id` per session (mirroring
`app/langgraph_followup.py::is_paused`) and branch to `resume_via_graph`
instead of a fresh `answer_data_via_graph_compat` call — a second,
separable piece of work with its own risk (two different resume
mechanisms would need to agree on which "owns" a given pause) that doesn't
change whether the GT proposal's core requirement — the runtime pipeline's
conditional branches and pause/resume running through LangGraph's own
primitives, not ad-hoc code — is met. It's tracked as explicit follow-up in
`tasks.md`, not silently dropped.

**What is and isn't verified**: `tests/test_pipeline_graph_cutover.py`
confirms (a) the pause→exception conversion in isolation, and (b) that
`_run_pipeline`'s flag branch actually calls the graph adapter when on and
`_answer_data` when off, using the same mocked-LLM/DB boundary
`tests/test_pipeline_graph.py` already established. What is **not**
verified, and cannot be from this environment: real LLM output quality and
real Postgres data through the graph path, across all 4 schemes — the
existing test suite for `pipeline_graph.py` is explicitly mocked-only (no
live LLM/DB, per `langgraph-full-pipeline-rewrite/tasks.md`'s own notes).
This is the actual remaining gate before flipping `PIPELINE_GRAPH_ENABLED`
to `True` in any real deployment, not a formality.

## 5. Scheme scale-out mechanics — implemented 2026-09-15

- `app/join_graph.py` reload: `POST /admin/reload-join-graph`
  (`app/routers/admin.py` — matches this repo's actual `/admin` prefix;
  not `/api/admin/...` as first sketched here) calls
  `join_graph.build(force=True)` so a new scheme's FK-augmentation YAML
  doesn't require a process restart.
- `schema_context.py` growth checkpoint: `app/scheme_registry.py::warn_if_scheme_count_high()`,
  called from `app/main.py`'s startup — a log warning (not a hard limit)
  once the in-memory registry's scheme count exceeds
  `SCHEME_COUNT_WARN_THRESHOLD` (10, a judgment call, not a measured
  cliff — see that function's own docstring) — pointing at
  `schema-retrieval-reranking`/`sql-generation-vector-fewshot` as the
  actual fix, so it isn't silently forgotten as schemes 5-25 get added one
  at a time. Reads the registry directly, not `app.schemes`, so it needs
  no DB round-trip at startup for a log line.
