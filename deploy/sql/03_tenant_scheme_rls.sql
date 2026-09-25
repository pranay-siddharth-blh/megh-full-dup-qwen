-- ============================================================================
-- Tenant/scheme Row-Level Security
-- openspec/changes/multi-tenant-rls-scheme-scaleout
--
-- WHY THIS EXISTS
--   Today, tenant isolation is 100% application-level: every admin-list
--   query builds its own `WHERE tenant_id = $N` in Python, and passing
--   tenant_id=None returns every tenant's rows (no server-side default-
--   deny). The curated scheme-data warehouse (MGNREGA/PMAY-G/Focus Plus/
--   CM Elevate) has never been tenant-partitioned at all. This script adds
--   a second, independent enforcement layer at the database itself, so an
--   application-level bug (a forgotten WHERE clause, a mis-resolved scope)
--   cannot leak another tenant's — or another scheme's — rows.
--
-- REVIEW BEFORE RUNNING. Requires a superuser (postgres / dbadmin), same
-- as deploy/sql/01_create_megh_app_role.sql. Idempotent: safe to re-run.
--
-- HARD PREREQUISITE, same as 01_create_megh_app_role.sql
--   RLS is meaningless against a superuser connection — BYPASSRLS is
--   implicit for superusers regardless of any policy defined here. This
--   script only has a real effect once the service connects as `megh_app`
--   (NOBYPASSRLS, already set by 01_create_megh_app_role.sql:41), which is
--   itself still blocked on production infra access as of this writing
--   (see project memory / phase-1-security-hardening item 3). Apply and
--   test this script against a disposable non-superuser Postgres first.
--
-- SECTION A — curated/semantic scheme data.
--   Safe to apply once app.schemes/app.tenant_schemes are populated (they
--   are created and seeded automatically by app/database/appdb.py + a startup call
--   to app/knowledge/scheme_registry.py::sync_to_db() — no manual step needed for
--   those two tables). The app's query path (app/api/routers/query.py wraps
--   /api/query in app.database.db.set_tenant_context()) is wired to set the
--   session GUCs this section's policies read.
--
--   IMPORTANT — Postgres cannot enable RLS on a VIEW, only on a real table
--   (`ALTER TABLE viewname ENABLE ROW LEVEL SECURITY` errors: "viewname is
--   not a table"). Per docs/schema_for_developers.md §6, every curated
--   object the app actually queries by name in generated SQL
--   (v_employment, v_expenditure, v_district_year_summary, v_pmay,
--   v_pmay_monthly_sanctions, v_focus_plus, v_cm_elevate,
--   v_cross_scheme_money_district_year, v_cross_scheme_village_coverage)
--   is a VIEW over one or more real fact tables. So this script enables
--   RLS on the 5 real per-scheme FACT tables only
--   (fact_mgnrega_employment, fact_mgnrega_expenditure, fact_pmay_house,
--   fact_focus_plus_disbursement, fact_cm_elevate_application) and relies
--   on Postgres applying that RLS transparently to any view built over
--   them — this is real, standard Postgres behavior, NOT a gap, but it
--   has one sharp edge that needs a live-DB check before this is trusted:
--
--   Row security on a table queried THROUGH a view is evaluated under the
--   VIEW'S OWNER's privileges, not the querying session's role. Table
--   owners bypass RLS on their own tables by default (RLS was designed so
--   an owner doing admin work isn't accidentally locked out) — so if
--   these fact tables and their views share an owner (near-certain: the
--   ETL/warehouse-loading role, NOT megh_app, which only has GRANT SELECT
--   per 01_create_megh_app_role.sql), querying through the view would see
--   ALL rows regardless of RLS policies, unless FORCE ROW LEVEL SECURITY
--   is also set (below) — which makes RLS apply even to the owning role.
--   FORCE does NOT help if that owner role additionally has the
--   BYPASSRLS attribute (superuser or explicitly granted) — BYPASSRLS
--   always wins. THIS SCRIPT CANNOT VERIFY THAT FROM HERE. Before trusting
--   Section A in any environment, run:
--     SELECT r.rolname, r.rolbypassrls
--     FROM pg_roles r WHERE r.rolname = (
--       SELECT tableowner FROM pg_tables
--       WHERE schemaname='curated' AND tablename='fact_mgnrega_employment'
--     );
--   If rolbypassrls is true, RLS on these fact tables (and every view over
--   them) is silently a no-op regardless of this script — that role's
--   BYPASSRLS must be revoked (if safe) or the tables re-owned to a
--   non-BYPASSRLS role before Section A means anything in that
--   environment. Task 3.4 in tasks.md exists specifically to catch this
--   with a real end-to-end read against a disposable Postgres, not by
--   inspecting this script alone.
--
-- SECTION B — app schema (app.users/conversations/etc).
--   DO NOT APPLY until every endpoint that reads these tables sets the
--   tenant context (app.database.db.set_tenant_context()) — as of this writing that
--   is only wired for /api/query. app/api/routers/admin.py, app/api/routers/
--   history.py, and the login flow in app/api/routers/auth.py all read/write
--   these tables today WITHOUT setting the context; enabling RLS here
--   before wiring them would make those endpoints see zero rows (a
--   superadmin's tenant_id=None "all tenants" queries would get nothing
--   back, since an unset GUC denies rather than matches). Left in this
--   file for review/completeness, commented out at the ENABLE step below.
-- ============================================================================

\set ON_ERROR_STOP on

-- ---------------------------------------------------------------------------
-- Section A.1 — helper function: does the current session's tenant have
-- access to this scheme? SECURITY DEFINER so it can read app.tenant_schemes
-- even though megh_app's grant on that table is scoped by RLS itself (see
-- Section B) once that's enabled — the function runs as its owner, not the
-- calling role, avoiding a chicken-and-egg policy-checking-a-policy problem.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.tenant_has_scheme_access(p_scheme_id TEXT)
RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = app, pg_temp
AS $$
    SELECT current_setting('app.tenant_bypass', true) = 'on'
        OR EXISTS (
            SELECT 1 FROM app.tenant_schemes
            WHERE tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::bigint
              AND scheme_id = p_scheme_id
        );
$$;

COMMENT ON FUNCTION app.tenant_has_scheme_access(TEXT) IS
    'RLS policy predicate for curated/semantic scheme-owned tables (openspec/changes/multi-tenant-rls-scheme-scaleout). current_setting(..., true) returns NULL when app/database/db.py has not set the GUC (a code path not yet wired through app.database.db.set_tenant_context()); NULLIF(...,'''')::bigint on an empty/NULL string is also NULL; the EXISTS check correctly evaluates to false (default-deny) in either case rather than erroring.';

-- ---------------------------------------------------------------------------
-- Section A.2 — policy generator. Reads curated.table_scheme_map (populate
-- this from scheme_registry.yaml's `tables:`/`shared:` fields — one row per
-- curated/semantic table, scheme_id NULL for shared tables) and emits one
-- ENABLE ROW LEVEL SECURITY + CREATE POLICY per scheme-owned table. This is
-- the mechanism that scales to 25 schemes without 25 hand-typed policies —
-- onboarding scheme #N is a table_scheme_map insert, not a SQL edit here.
--
-- curated.table_scheme_map itself needs CREATE privilege on the curated
-- schema, which megh_app does NOT have (SELECT-only, by design — see
-- 01_create_megh_app_role.sql section 2) — so, unlike app.schemes/
-- app.tenant_schemes, this table is created here, by a superuser, not by
-- app/database/appdb.py's runtime DDL.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS curated.table_scheme_map (
    table_schema TEXT NOT NULL,
    table_name   TEXT NOT NULL,
    scheme_id    TEXT,  -- NULL = shared/reference object, no RLS applied
    PRIMARY KEY (table_schema, table_name)
);
GRANT SELECT ON curated.table_scheme_map TO megh_app;

-- Seed from today's scheme_registry.yaml (4 real schemes) plus the shared
-- dimension/lookup tables — re-running this INSERT is idempotent via ON
-- CONFLICT. Onboarding scheme #5 onward: add its FACT table row(s) here
-- (or via an admin tool built on top of this table — out of scope for this
-- script) rather than editing the policy-generation DO block below.
--
-- This row set intentionally does NOT match scheme_registry.yaml's
-- `tables:` lists 1:1 — those lists exist for prompt/schema-retrieval
-- purposes and mix real fact tables, views over them, and dimension
-- tables together. This table's job is different: it's the DB-enforcement
-- map, so only rows the generator below can act on (real tables) carry a
-- non-NULL scheme_id. See the two categories called out below.
--
-- Category 1 — real per-scheme FACT tables: RLS-gated (scheme_id set).
-- These are the only rows the generator DO block turns into policies.
INSERT INTO curated.table_scheme_map (table_schema, table_name, scheme_id) VALUES
    ('curated', 'fact_mgnrega_employment',      'MGNREGA'),
    ('curated', 'fact_mgnrega_expenditure',     'MGNREGA'),
    ('curated', 'fact_pmay_house',              'PMAY-G'),
    ('curated', 'fact_focus_plus_disbursement', 'Focus Plus'),
    ('curated', 'fact_cm_elevate_application',  'CM Elevate')
ON CONFLICT (table_schema, table_name) DO UPDATE SET scheme_id = EXCLUDED.scheme_id;

-- Category 2 — VIEWS over the Category-1 facts (documentation only; the
-- generator below skips these via a live pg_class.relkind check, since
-- Postgres cannot ALTER TABLE ... ENABLE ROW LEVEL SECURITY on a view).
-- Protected transitively once Category 1's RLS + FORCE (below) is
-- confirmed effective per this file's header note on view ownership.
-- v_cross_scheme_money_district_year and v_cross_scheme_village_coverage
-- are UNION/JOIN compositions over MULTIPLE facts (MGNREGA + PMAY-G per
-- docs/DATA_MODEL.md) — a tenant missing one scheme's grant sees that
-- scheme's branch return zero rows (UNION) or NULL-out that scheme's
-- columns (coverage's per-village join), never an error and never the
-- other scheme's real data. scheme_id is set here to the scheme it most
-- directly surfaces, or NULL where multiple/none apply — purely
-- descriptive, the generator ignores it for non-table relations.
INSERT INTO curated.table_scheme_map (table_schema, table_name, scheme_id) VALUES
    ('curated', 'v_employment',              'MGNREGA'),
    ('curated', 'v_expenditure',             'MGNREGA'),
    ('curated', 'v_district_year_summary',   'MGNREGA'),
    ('curated', 'v_pmay',                    'PMAY-G'),
    ('curated', 'v_pmay_monthly_sanctions',  'PMAY-G'),
    ('curated', 'v_focus_plus',              'Focus Plus'),
    ('curated', 'v_cm_elevate',              'CM Elevate'),
    ('curated', 'v_cross_scheme_money_district_year', NULL),
    ('curated', 'v_cross_scheme_village_coverage',    NULL)
ON CONFLICT (table_schema, table_name) DO UPDATE SET scheme_id = EXCLUDED.scheme_id;

-- Category 3 — dimension/lookup tables genuinely left open (real tables,
-- but scheme_id NULL on purpose, not by omission): dim_pmay_house_status
-- and dim_cm_elevate_scheme carry only small reference/status vocabularies
-- (a handful of status labels; the list of 15 CM Elevate sub-schemes) —
-- no beneficiary, geography, or money data — so gating them would add
-- friction (a scheme filter on prompts/joins) without closing any real
-- leak. Same reasoning as dim_scheme/dim_year/dim_geography, already
-- shared in scheme_registry.yaml.
INSERT INTO curated.table_scheme_map (table_schema, table_name, scheme_id) VALUES
    ('curated', 'dim_pmay_house_status',     NULL),
    ('curated', 'dim_cm_elevate_scheme',     NULL),
    ('curated', 'dim_scheme',                NULL),
    ('curated', 'dim_year',                  NULL),
    ('curated', 'dim_geography',             NULL),
    ('curated', 'dim_geography_alias',       NULL),
    ('curated', 'bridge_geography_source',   NULL)
ON CONFLICT (table_schema, table_name) DO UPDATE SET scheme_id = EXCLUDED.scheme_id;

-- Generate and apply one ENABLE + FORCE ROW LEVEL SECURITY + CREATE POLICY
-- per scheme-owned row that is a REAL TABLE (pg_class.relkind = 'r'/'p') —
-- checked live rather than trusted from a static column, so a future
-- onboarding mistake (mapping a scheme_id to a view by accident) degrades
-- to a skipped NOTICE, not a broken migration. FORCE is required, not
-- optional — see this file's header note on view-owner RLS bypass.
DO $$
DECLARE
    r RECORD;
    v_relkind "char";
BEGIN
    FOR r IN SELECT table_schema, table_name, scheme_id
             FROM curated.table_scheme_map
             WHERE scheme_id IS NOT NULL
    LOOP
        SELECT c.relkind INTO v_relkind
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = r.table_schema AND c.relname = r.table_name;

        IF v_relkind IS NULL THEN
            RAISE NOTICE 'table_scheme_map: %.% not found in this database — skipped',
                r.table_schema, r.table_name;
            CONTINUE;
        ELSIF v_relkind NOT IN ('r', 'p') THEN
            RAISE NOTICE 'table_scheme_map: %.% is relkind=% (not an ordinary table) — RLS not applicable directly; if it is a view over a Category-1 fact table, it is protected transitively instead. Skipped.',
                r.table_schema, r.table_name, v_relkind;
            CONTINUE;
        END IF;

        EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', r.table_schema, r.table_name);
        EXECUTE format('ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY', r.table_schema, r.table_name);
        EXECUTE format('DROP POLICY IF EXISTS scheme_access ON %I.%I', r.table_schema, r.table_name);
        EXECUTE format(
            'CREATE POLICY scheme_access ON %I.%I USING (app.tenant_has_scheme_access(%L))',
            r.table_schema, r.table_name, r.scheme_id
        );
    END LOOP;
END
$$;

-- ---------------------------------------------------------------------------
-- Section B — app schema RLS.
--
-- Re-audited 2026-09-15 (multi-tenant-rls-scheme-scaleout tasks.md 2.2):
-- this section's own comment ("admin.py/history.py/auth.py are not wired to
-- set_tenant_context() yet") had gone stale — app/api/routers/admin.py and
-- app/api/routers/history.py already depend on app.api.deps.require_admin/
-- require_user, which chain through app.api.deps.tenant_scoped, which already
-- calls set_tenant_context()/reset_tenant_context() around every request.
-- The two real gaps found on re-verification, now fixed:
--   1. app/api/routers/auth.py's login()/bootstrap() — no scope exists yet at
--      that point (that's what they produce), so there is no tenant to
--      derive context from; the username lookup is inherently cross-tenant.
--      Fixed: both now wrap their body in set_tenant_context(None, bypass=True).
--   2. app/main.py's startup sequence — appdb.ensure_schema()'s user-seed and
--      _sync_scheme_entitlements()'s default-tenant grant-seed both write
--      real tenant_id rows with no request/scope at all. Fixed: startup now
--      wraps both in the same bypass=True context.
--
-- FORCE is required here too, and for a DIFFERENT reason than Section A:
-- unlike curated/semantic (megh_app only has SELECT, never owns those
-- tables), megh_app IS the owner of every app.* table (it creates them via
-- CREATE TABLE IF NOT EXISTS, granted CREATE ON SCHEMA app) — a table
-- owner bypasses RLS on their own tables by default, so without FORCE this
-- section would be a complete no-op precisely because it "worked".
-- ---------------------------------------------------------------------------
ALTER TABLE app.users              ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.users              FORCE ROW LEVEL SECURITY;
ALTER TABLE app.login_events       ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.login_events       FORCE ROW LEVEL SECURITY;
ALTER TABLE app.conversations      ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.conversations      FORCE ROW LEVEL SECURITY;
ALTER TABLE app.conversation_turns ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.conversation_turns FORCE ROW LEVEL SECURITY;
ALTER TABLE app.query_audit        ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.query_audit        FORCE ROW LEVEL SECURITY;
ALTER TABLE app.tenant_schemes     ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.tenant_schemes     FORCE ROW LEVEL SECURITY;

-- tenant_id is nullable on login_events/query_audit (a pre-login failed
-- attempt, or a request that never resolved a user) — a NULL row matches
-- no tenant under this predicate, same default-deny posture as the
-- curated-data policy in Section A, not a special case needing its own
-- clause. bypass covers both super_admin (app/api/deps.py::tenant_scoped) and
-- the two system-level cases above (login/bootstrap, startup seeding).
DROP POLICY IF EXISTS tenant_isolation ON app.users;
CREATE POLICY tenant_isolation ON app.users USING (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::bigint
    OR current_setting('app.tenant_bypass', true) = 'on'
);
DROP POLICY IF EXISTS tenant_isolation ON app.login_events;
CREATE POLICY tenant_isolation ON app.login_events USING (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::bigint
    OR current_setting('app.tenant_bypass', true) = 'on'
);
DROP POLICY IF EXISTS tenant_isolation ON app.conversations;
CREATE POLICY tenant_isolation ON app.conversations USING (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::bigint
    OR current_setting('app.tenant_bypass', true) = 'on'
);
DROP POLICY IF EXISTS tenant_isolation ON app.conversation_turns;
CREATE POLICY tenant_isolation ON app.conversation_turns USING (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::bigint
    OR current_setting('app.tenant_bypass', true) = 'on'
);
DROP POLICY IF EXISTS tenant_isolation ON app.query_audit;
CREATE POLICY tenant_isolation ON app.query_audit USING (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::bigint
    OR current_setting('app.tenant_bypass', true) = 'on'
);
DROP POLICY IF EXISTS tenant_isolation ON app.tenant_schemes;
CREATE POLICY tenant_isolation ON app.tenant_schemes USING (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::bigint
    OR current_setting('app.tenant_bypass', true) = 'on'
);

-- ---------------------------------------------------------------------------
-- Verify (run after Section A above)
-- ---------------------------------------------------------------------------
\echo ''
\echo '=== curated/semantic tables with RLS enabled+forced ==='
SELECT n.nspname AS schema, c.relname AS table,
       c.relrowsecurity AS rls_enabled, c.relforcerowsecurity AS rls_forced
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname IN ('curated', 'semantic') AND c.relkind = 'r' AND c.relrowsecurity
ORDER BY c.relname;
\echo 'Expected exactly the 5 Category-1 fact tables above, both columns true.'

\echo ''
\echo '=== view-owner BYPASSRLS check (the sharp edge this file''s header warns about) ==='
SELECT v.schemaname, v.viewname, v.viewowner, r.rolbypassrls
FROM pg_views v
JOIN pg_roles r ON r.rolname = v.viewowner
WHERE v.schemaname = 'curated'
  AND v.viewname IN (SELECT table_name FROM curated.table_scheme_map)
ORDER BY v.viewname;
\echo 'Expected: rolbypassrls = false for every row. If any is true, RLS on the'
\echo 'fact tables is a no-op for that view regardless of Section A above —'
\echo 'fix the owning role before trusting this migration in this environment.'

\echo ''
\echo 'Manual read-path check — run as megh_app (NOT postgres), with a tenant'
\echo 'granted MGNREGA only, e.g.:'
\echo '  SELECT set_config(''app.current_tenant_id'', ''<that tenant_id>'', false);'
\echo '  SELECT set_config(''app.tenant_bypass'', ''off'', false);'
\echo '  SELECT count(*) FROM curated.fact_mgnrega_employment;        -- > 0, granted'
\echo '  SELECT count(*) FROM curated.fact_pmay_house;                -- = 0, not granted'
\echo '  SELECT count(*) FROM curated.v_pmay;                         -- = 0 (via the view)'
\echo '  SELECT DISTINCT scheme_code FROM curated.v_cross_scheme_money_district_year;'
\echo '                                                  -- only MGNREGA, PMAY-G branch empty'
\echo '  SELECT count(*) FROM curated.v_cross_scheme_village_coverage'
\echo '    WHERE pmay_houses IS NOT NULL;                -- = 0 (PMAY column NULLed out)'
\echo 'This is the real end-to-end proof — task 3.4 in tasks.md — not just the'
\echo 'catalog checks above, which only confirm policies EXIST, not that they work.'
