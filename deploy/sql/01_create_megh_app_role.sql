-- ============================================================================
-- megh_app — the least-privilege role the NLP service's APP pool connects as
-- (DATABASE_URL). Model-generated SQL does NOT run on this login: it has its
-- own pool as megh_readonly (READONLY_DATABASE_URL, 03_readonly_role.sql).
--
-- WHY THIS EXISTS
--   The service used to connect as `postgres` (superuser) for everything, so
--   every statement the LLM generated ran with full write and DDL privileges,
--   held back only by the SQL check in the application.
--
--   The service also writes its own bookkeeping in the `app` schema (users,
--   sessions, chat history, audit trail, LangGraph checkpoints) on every login
--   and every query, so it needs one login that can write `app.*`. That is
--   megh_app: read-only on the scheme data, owner of `app.*`.
--
--   megh_app OWNS the app.* tables (section 3): app.appdb.ensure_schema() runs
--   ALTER TABLE ... ADD COLUMN IF NOT EXISTS at every startup, and Postgres
--   requires ownership for that even when the column already exists; the
--   LangGraph checkpointer's setup() is the same.
--
-- REVIEW BEFORE RUNNING. Requires a superuser (postgres / dbadmin). Run it as
-- the role that owns curated.* / semantic.* (postgres on megh_db) so the
-- default privileges below cover the tables the ETL creates later.
-- Idempotent: safe to re-run.
-- ============================================================================

\set ON_ERROR_STOP on

-- ---------------------------------------------------------------------------
-- 1. The role
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'megh_app') THEN
        -- REPLACE the password before running. Generate one with:
        --   python -c "import secrets; print(secrets.token_urlsafe(32))"
        CREATE ROLE megh_app LOGIN PASSWORD 'REPLACE_ME_WITH_A_STRONG_PASSWORD';
        RAISE NOTICE 'created role megh_app';
    ELSE
        RAISE NOTICE 'role megh_app already exists — leaving password untouched';
    END IF;
END
$$;

-- Belt and braces: this role must never acquire these, even by inheritance.
ALTER ROLE megh_app NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

-- Keep query cost bounded at the role level, independent of the app's own
-- SQL_EXECUTION_TIMEOUT_MS.
ALTER ROLE megh_app SET statement_timeout = '30s';
ALTER ROLE megh_app SET idle_in_transaction_session_timeout = '60s';

-- ---------------------------------------------------------------------------
-- 2. Scheme data — READ ONLY.
--    The app pool's own trusted queries (entity resolution, scheme stats,
--    schema introspection) read these; it never writes them.
-- ---------------------------------------------------------------------------
GRANT CONNECT ON DATABASE megh_db TO megh_app;

GRANT USAGE ON SCHEMA curated  TO megh_app;
GRANT USAGE ON SCHEMA semantic TO megh_app;

GRANT SELECT ON ALL TABLES    IN SCHEMA curated  TO megh_app;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA curated  TO megh_app;
GRANT SELECT ON ALL TABLES    IN SCHEMA semantic TO megh_app;

-- Tables added to those schemas later are read-only for this role too.
-- NOTE: default privileges apply per granting role (the one running this). If
-- the ETL writes as a different owner, repeat these with FOR ROLE <that_owner>.
ALTER DEFAULT PRIVILEGES IN SCHEMA curated  GRANT SELECT ON TABLES TO megh_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA semantic GRANT SELECT ON TABLES TO megh_app;

-- Explicitly NOT granted on curated/semantic: INSERT, UPDATE, DELETE, TRUNCATE,
-- REFERENCES, TRIGGER, CREATE. Revoked too, in case an earlier grant exists.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
    ON ALL TABLES IN SCHEMA curated, semantic FROM megh_app;
REVOKE CREATE ON SCHEMA curated, semantic FROM megh_app;

-- pg_trgm lives in `public`: the entity resolver's fuzzy village match calls
-- similarity(). On megh_db (PG 18) PUBLIC has no USAGE on `public`, so it must
-- be granted. USAGE only — no CREATE.
GRANT USAGE ON SCHEMA public TO megh_app;
REVOKE CREATE ON SCHEMA public FROM megh_app;

-- ---------------------------------------------------------------------------
-- 3. Application schema — OWNED by megh_app.
--    app.users, app.tenants, app.login_events, app.conversations,
--    app.conversation_turns, app.query_audit, app.schemes, app.tenant_schemes,
--    app.checkpoint* (LangGraph).
-- ---------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS app;

GRANT USAGE, CREATE ON SCHEMA app TO megh_app;

-- Hand every existing table / view / standalone sequence to megh_app. Sequences
-- owned by a table column (SERIAL / IDENTITY) move with their table.
DO $$
DECLARE
    obj record;
BEGIN
    FOR obj IN
        SELECT c.relname, c.relkind
        FROM   pg_class c
        JOIN   pg_namespace n ON n.oid = c.relnamespace
        WHERE  n.nspname = 'app'
          AND  c.relkind IN ('r', 'p', 'v', 'm', 'f')
          AND  pg_get_userbyid(c.relowner) <> 'megh_app'
    LOOP
        EXECUTE format('ALTER %s app.%I OWNER TO megh_app',
                       CASE obj.relkind WHEN 'v' THEN 'VIEW'
                                        WHEN 'm' THEN 'MATERIALIZED VIEW'
                                        WHEN 'f' THEN 'FOREIGN TABLE'
                                        ELSE 'TABLE' END,
                       obj.relname);
    END LOOP;
    FOR obj IN
        SELECT c.relname
        FROM   pg_class c
        JOIN   pg_namespace n ON n.oid = c.relnamespace
        WHERE  n.nspname = 'app' AND c.relkind = 'S'
          AND  pg_get_userbyid(c.relowner) <> 'megh_app'
          AND  NOT EXISTS (SELECT 1 FROM pg_depend d
                           WHERE d.objid = c.oid AND d.deptype IN ('a', 'i'))
    LOOP
        EXECUTE format('ALTER SEQUENCE app.%I OWNER TO megh_app', obj.relname);
    END LOOP;
    FOR obj IN
        SELECT p.oid::regprocedure AS sig
        FROM   pg_proc p
        JOIN   pg_namespace n ON n.oid = p.pronamespace
        WHERE  n.nspname = 'app' AND pg_get_userbyid(p.proowner) <> 'megh_app'
    LOOP
        EXECUTE format('ALTER ROUTINE %s OWNER TO megh_app', obj.sig);
    END LOOP;
END
$$;

-- ---------------------------------------------------------------------------
-- 4. Lock down everything else
-- ---------------------------------------------------------------------------
-- No access to raw / staging / meta (ETL and data-team schemas).
DO $$
DECLARE
    s text;
BEGIN
    FOREACH s IN ARRAY ARRAY['raw', 'staging', 'meta'] LOOP
        IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = s) THEN
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM megh_app', s);
            EXECUTE format('REVOKE ALL ON SCHEMA %I FROM megh_app', s);
        END IF;
    END LOOP;
END
$$;

-- ---------------------------------------------------------------------------
-- 5. Verify (run after the grants above)
-- ---------------------------------------------------------------------------
\echo ''
\echo '=== megh_app effective privileges ==='

SELECT 'schema USAGE' AS check,
       n.nspname      AS object,
       has_schema_privilege('megh_app', n.nspname, 'USAGE')  AS usage,
       has_schema_privilege('megh_app', n.nspname, 'CREATE') AS create
FROM   pg_namespace n
WHERE  n.nspname IN ('app', 'curated', 'semantic', 'public', 'raw', 'staging', 'meta')
ORDER  BY n.nspname;

SELECT 'scheme data must be read-only' AS check,
       count(*) FILTER (WHERE NOT has_table_privilege('megh_app', c.oid, 'SELECT')) AS unreadable,
       count(*) FILTER (WHERE has_table_privilege('megh_app', c.oid, 'INSERT')
                           OR has_table_privilege('megh_app', c.oid, 'UPDATE')
                           OR has_table_privilege('megh_app', c.oid, 'DELETE')
                           OR has_table_privilege('megh_app', c.oid, 'TRUNCATE')) AS writable
FROM   pg_class c
JOIN   pg_namespace n ON n.oid = c.relnamespace
WHERE  n.nspname IN ('curated', 'semantic') AND c.relkind IN ('r', 'v', 'm', 'p');

SELECT 'app schema must be owned' AS check,
       c.relname                  AS object,
       pg_get_userbyid(c.relowner) AS owner
FROM   pg_class c
JOIN   pg_namespace n ON n.oid = c.relnamespace
WHERE  n.nspname = 'app' AND c.relkind IN ('r', 'p')
ORDER  BY c.relname;

\echo ''
\echo 'Expected: curated/semantic -> unreadable = 0, writable = 0'
\echo '          app.*            -> owner = megh_app'
\echo '          raw/staging/meta -> usage = f'
\echo ''
\echo 'Then set in .env:'
\echo '  DATABASE_URL=postgresql://megh_app:<password>@10.48.242.4:5432/megh_db'
\echo 'and run 03_readonly_role.sql for READONLY_DATABASE_URL, then restart the service.'
