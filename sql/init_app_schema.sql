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
