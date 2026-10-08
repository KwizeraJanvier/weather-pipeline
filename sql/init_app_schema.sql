-- App-level tables (users, sessions) live in their own schema, deliberately
-- separate from raw/staging/marts, so the web app's auth data is never
-- mixed with pipeline data and is easy to exclude from anything read-only.
CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.users (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('admin', 'viewer')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Security-relevant events: signups, logins (success and failure), logouts,
-- and every SQL query run through the admin query tool (including ones
-- blocked by the SELECT-only check - a pattern of blocked attempts is
-- itself a signal worth seeing). user_id is nullable because a failed
-- login attempt may not correspond to a real user.
CREATE TABLE IF NOT EXISTS app.audit_log (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES app.users(id),
    email TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- This file gets run as the Postgres superuser (needed for CREATE ROLE
-- below), which would otherwise leave these tables owned by the superuser
-- instead of `warehouse` - the role the app itself connects as. Grant
-- explicitly so it doesn't matter which role actually ran this script.
GRANT ALL ON SCHEMA app TO warehouse;
GRANT ALL ON ALL TABLES IN SCHEMA app TO warehouse;
GRANT ALL ON ALL SEQUENCES IN SCHEMA app TO warehouse;

-- A dedicated, genuinely read-only Postgres role for the "run custom SQL"
-- feature in the web app. The app's custom-query endpoint ALWAYS connects
-- as this role, never as the main `warehouse` user - so even if a query
-- somehow got past the app's own SELECT-only check, Postgres itself would
-- refuse any write. It also has no grants on the `app` schema at all, so a
-- query run through the UI can never read another user's password hash.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'app_readonly') THEN
        CREATE ROLE app_readonly LOGIN PASSWORD 'app_readonly';
    END IF;
END
$$;

ALTER ROLE app_readonly SET statement_timeout = '5s';

GRANT USAGE ON SCHEMA raw, staging, marts TO app_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA raw, staging, marts TO app_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA raw, staging, marts
    GRANT SELECT ON TABLES TO app_readonly;

REVOKE ALL ON SCHEMA app FROM app_readonly, PUBLIC;
