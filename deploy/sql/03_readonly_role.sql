-- ============================================================================
-- megh_readonly — the SELECT-only role model-generated SQL runs as
-- (READONLY_DATABASE_URL, the read-only pool in app/db.py).
--
-- WHAT IT ENFORCES (in the database, whatever the application lets through)
--   - SELECT on curated.* and semantic.* — nothing else: no INSERT / UPDATE /
--     DELETE / TRUNCATE, no CREATE, no access to app / raw / staging / meta /
--     public.
--   - default_transaction_read_only = on, so every transaction on this login
--     is READ ONLY (app/db.py also opens each one with BEGIN READ ONLY).
--   - search_path = curated, semantic.
--   - statement_timeout, so a runaway generated query cannot pin a backend.
--
-- megh_readonly already exists on megh_db (2026-10-15) but was missing SELECT
-- on curated.v_cm_elevate and curated.fact_cm_elevate_application (no default
-- privileges were set), so CM Elevate questions would fail on it. Section 2
-- grants every current table and sets default privileges for future ones.
--
-- REVIEW BEFORE RUNNING. Requires a superuser (postgres / dbadmin). Run it as
-- the role that owns curated.* / semantic.* (postgres on megh_db).
-- Idempotent: safe to re-run.
-- ============================================================================

\set ON_ERROR_STOP on

-- ---------------------------------------------------------------------------
-- 1. The role
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'megh_readonly') THEN
        -- REPLACE the password before running. Generate one with:
        --   python -c "import secrets; print(secrets.token_urlsafe(32))"
        CREATE ROLE megh_readonly LOGIN PASSWORD 'REPLACE_ME_WITH_A_STRONG_PASSWORD';
        RAISE NOTICE 'created role megh_readonly';
    ELSE
        RAISE NOTICE 'role megh_readonly already exists — leaving password untouched';
    END IF;
END
$$;

ALTER ROLE megh_readonly NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

ALTER ROLE megh_readonly SET default_transaction_read_only = on;
ALTER ROLE megh_readonly SET search_path = curated, semantic;
ALTER ROLE megh_readonly SET statement_timeout = '30s';
ALTER ROLE megh_readonly SET idle_in_transaction_session_timeout = '60s';

-- ---------------------------------------------------------------------------
-- 2. curated / semantic — SELECT only
-- ---------------------------------------------------------------------------
GRANT CONNECT ON DATABASE megh_db TO megh_readonly;

GRANT USAGE  ON SCHEMA curated, semantic TO megh_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA curated, semantic TO megh_readonly;

-- Tables the ETL adds later. Default privileges apply per granting role (the
-- one running this); if the ETL writes as another owner, repeat with
-- FOR ROLE <that_owner>.
ALTER DEFAULT PRIVILEGES IN SCHEMA curated  GRANT SELECT ON TABLES TO megh_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA semantic GRANT SELECT ON TABLES TO megh_readonly;

REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
    ON ALL TABLES IN SCHEMA curated, semantic FROM megh_readonly;
REVOKE CREATE ON SCHEMA curated, semantic FROM megh_readonly;

-- ---------------------------------------------------------------------------
-- 3. Everything else — no access
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    s text;
BEGIN
    FOREACH s IN ARRAY ARRAY['app', 'raw', 'staging', 'meta', 'public'] LOOP
        IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = s) THEN
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM megh_readonly', s);
            EXECUTE format('REVOKE ALL ON SCHEMA %I FROM megh_readonly', s);
        END IF;
    END LOOP;
END
$$;

-- ---------------------------------------------------------------------------
-- 4. Verify
-- ---------------------------------------------------------------------------
\echo ''
\echo '=== megh_readonly effective privileges ==='

SELECT rolname, rolsuper, rolbypassrls, rolconfig
FROM   pg_roles WHERE rolname = 'megh_readonly';

SELECT 'schema access' AS check,
       n.nspname       AS object,
       has_schema_privilege('megh_readonly', n.nspname, 'USAGE')  AS usage,
       has_schema_privilege('megh_readonly', n.nspname, 'CREATE') AS create
FROM   pg_namespace n
WHERE  n.nspname IN ('app', 'curated', 'semantic', 'public', 'raw', 'staging', 'meta')
ORDER  BY n.nspname;

SELECT 'curated/semantic must be select-only' AS check,
       count(*) FILTER (WHERE NOT has_table_privilege('megh_readonly', c.oid, 'SELECT')) AS unreadable,
       count(*) FILTER (WHERE has_table_privilege('megh_readonly', c.oid, 'INSERT')
                           OR has_table_privilege('megh_readonly', c.oid, 'UPDATE')
                           OR has_table_privilege('megh_readonly', c.oid, 'DELETE')
                           OR has_table_privilege('megh_readonly', c.oid, 'TRUNCATE')) AS writable
FROM   pg_class c
JOIN   pg_namespace n ON n.oid = c.relnamespace
WHERE  n.nspname IN ('curated', 'semantic') AND c.relkind IN ('r', 'v', 'm', 'p');

\echo ''
\echo 'Expected: rolsuper = f, rolconfig has default_transaction_read_only=on'
\echo '          curated/semantic -> usage = t, create = f, unreadable = 0, writable = 0'
\echo '          app/raw/staging/meta/public -> usage = f'
\echo ''
\echo 'Then set in .env:'
\echo '  READONLY_DATABASE_URL=postgresql://megh_readonly:<password>@10.48.242.4:5432/megh_db'
\echo 'and restart the service.'
